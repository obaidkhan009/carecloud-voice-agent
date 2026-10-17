# Voice AI Patient Registration Agent — Implementation Spec

CareCloud take-home assessment (AI Engineer). Time budget: 3 hours. Target: a simple system that works
flawlessly end to end, not an over-engineered one.

Deliverables to send back to Muhammad Akhtar (HR):
1. Repository URL (GitHub)
2. US phone number to call
3. API base URL
4. Dashboard URL (HR asked for this explicitly, so it is NOT optional for us)
5. Test notes / credentials

---

## 1. Stack decision (and why)

| Layer | Choice | Reason |
|---|---|---|
| Telephony + STT + TTS + turn-taking | **Vapi** | Free US number on the trial, handles interruptions/barge-in, out-of-order answers and latency for us. The PDF explicitly recommends it as "the fastest path". |
| LLM | **OpenAI gpt-4o-mini** (via Vapi's built-in provider) | Lowest latency on Vapi, native tool calling, cheap. Claude Sonnet is a one-line swap in the assistant config if desired. |
| Backend / REST API | **Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2** | Obaid's primary stack; Pydantic gives server-side validation + 422 responses for free. |
| Database | **PostgreSQL** on Railway (prod), **SQLite** locally | One `DATABASE_URL` env var switches engines. Postgres on Railway survives redeploys without a volume. |
| Dashboard | Single static HTML page served by FastAPI at `/dashboard` (vanilla JS + fetch) | No build step, one file, zero extra deploy. |
| Hosting | **Railway** (API + Postgres) | Public HTTPS URL for the Vapi webhook, free tier, Postgres add-on in one click. ngrok as fallback for local testing. |
| Tests | **pytest + httpx** against SQLite in-memory | Bonus points, and protects the API while iterating on the voice side. |

Trade-off logged for README: using Vapi's hosted LLM loop instead of a "custom LLM" endpoint means the
prompt and tool definitions live in a JSON config in the repo (`vapi/assistant.json`) and are pushed to Vapi
via a script. We keep full control of validation, persistence and business logic in our own webhook.

---

## 2. Architecture

```
Caller ──PSTN──> Vapi (number, Deepgram STT, 11Labs/Vapi TTS, gpt-4o-mini tool loop)
                      │
                      │  HTTPS POST  /vapi/webhook   (tool-calls, end-of-call-report)
                      ▼
            FastAPI app (Railway)
            ├── routers/patients.py   ──> services/patients.py ──> db (SQLAlchemy) ──> PostgreSQL
            ├── routers/vapi.py       ──> same services layer (no HTTP self-call)
            ├── routers/calls.py      (GET /calls — transcripts)
            └── static/dashboard.html (GET /dashboard)
```

Separation of concerns:
- **Telephony / voice** = Vapi config only (`vapi/assistant.json`, `vapi/system_prompt.md`).
- **LLM logic** = system prompt + tool schemas. No business rules in the prompt beyond conversational behaviour.
- **Data layer** = `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `services/patients.py` (CRUD + validation).
- **API** = thin routers that return the `{ "data": ..., "error": null }` envelope.
- The Vapi webhook calls the **same service functions** as the REST routes, so validation is enforced once, server-side.

---

## 3. Repository layout

```
carecloud-voice-agent/
├── README.md
├── SPEC.md                      (this file)
├── .env.example
├── .gitignore
├── requirements.txt
├── Procfile                     web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
├── railway.json                 (optional, build/start settings)
├── app/
│   ├── main.py                  FastAPI app, middleware, envelope error handlers, router mounting, startup seed
│   ├── config.py                pydantic-settings: DATABASE_URL, VAPI_SECRET, LOG_LEVEL, SEED_DATA
│   ├── db.py                    engine, SessionLocal, Base, get_db dependency
│   ├── models.py                Patient, CallLog ORM models
│   ├── schemas.py               PatientCreate, PatientUpdate, PatientOut, Envelope, validators
│   ├── validation.py            pure functions: normalize_phone, validate_dob, validate_zip, STATES set, etc.
│   ├── services/
│   │   ├── patients.py          create / get / list / update / soft_delete / find_by_phone
│   │   └── calls.py             persist end-of-call transcript + summary
│   ├── routers/
│   │   ├── patients.py          REST endpoints
│   │   ├── vapi.py              POST /vapi/webhook  (tool dispatch + end-of-call-report)
│   │   ├── calls.py             GET /calls, GET /calls/{id}
│   │   └── health.py            GET /health
│   ├── seed.py                  2 demo patients, idempotent
│   └── static/dashboard.html
├── vapi/
│   ├── system_prompt.md         the full, commented system prompt (graded!)
│   ├── assistant.json           Vapi assistant definition: model, voice, transcriber, tools, serverUrl
│   └── push_assistant.py        creates/updates the assistant via Vapi REST API using VAPI_API_KEY
├── tests/
│   ├── conftest.py              SQLite in-memory app fixture
│   ├── test_patients_api.py
│   ├── test_validation.py
│   └── test_vapi_webhook.py
└── logs/                        (gitignored) conversation logs if LOG_TO_FILE=1
```

---

## 4. Data model

### `patients` table

| Column | Type | Constraint |
|---|---|---|
| patient_id | UUID PK | default uuid4 |
| first_name | VARCHAR(50) NOT NULL | regex `^[A-Za-z][A-Za-z'\- ]{0,49}$` (checked in Pydantic + CHECK length) |
| last_name | VARCHAR(50) NOT NULL | same |
| date_of_birth | DATE NOT NULL | `<= today` (CHECK + Pydantic); API accepts `MM/DD/YYYY` or ISO, stores DATE, returns `MM/DD/YYYY` |
| sex | VARCHAR(20) NOT NULL | Enum: `Male`, `Female`, `Other`, `Decline to Answer` (DB Enum / CHECK) |
| phone_number | VARCHAR(10) NOT NULL | normalized to 10 digits, index (non-unique, soft-deleted rows may repeat) |
| email | VARCHAR(254) NULL | Pydantic `EmailStr` |
| address_line_1 | VARCHAR(200) NOT NULL | |
| address_line_2 | VARCHAR(200) NULL | |
| city | VARCHAR(100) NOT NULL | 1–100 |
| state | CHAR(2) NOT NULL | in 50 states + DC (+ PR, GU, VI, AS, MP) |
| zip_code | VARCHAR(10) NOT NULL | `^\d{5}(-\d{4})?$` |
| insurance_provider | VARCHAR(100) NULL | |
| insurance_member_id | VARCHAR(50) NULL | `^[A-Za-z0-9\-]+$` |
| preferred_language | VARCHAR(50) NOT NULL | default `English` |
| emergency_contact_name | VARCHAR(100) NULL | |
| emergency_contact_phone | VARCHAR(10) NULL | 10 digits |
| created_at | TIMESTAMPTZ NOT NULL | server default `now()` UTC |
| updated_at | TIMESTAMPTZ NOT NULL | `onupdate=now()` |
| deleted_at | TIMESTAMPTZ NULL | soft delete; all reads filter `deleted_at IS NULL` |

### `call_logs` table (bonus: transcript linked to patient)

| Column | Type |
|---|---|
| id | UUID PK |
| vapi_call_id | VARCHAR(64) unique |
| patient_id | UUID FK -> patients NULL |
| caller_number | VARCHAR(20) NULL |
| started_at / ended_at | TIMESTAMPTZ |
| ended_reason | VARCHAR(100) |
| transcript | TEXT |
| summary | TEXT |
| collected_payload | JSON (the final data the agent tried to save) |
| created_at | TIMESTAMPTZ |

Seed data: two patients (e.g. "Jane Doe", DOB 03/14/1985, phone 2015550123; "Carlos Rivera", Spanish
preferred language) inserted on startup if the table is empty and `SEED_DATA=true`.

---

## 5. REST API contract

Base: `https://<app>.up.railway.app`. All responses: `{"data": <object|array|null>, "error": <null|{"code","message","details"}>}`.

| Method | Path | 2xx | Errors |
|---|---|---|---|
| GET | `/health` | 200 `{status:"ok", db:"ok"}` | 500 |
| GET | `/patients?last_name=&date_of_birth=&phone_number=&limit=&offset=` | 200 array | 400 bad filter |
| GET | `/patients/{id}` | 200 | 400 invalid UUID, 404 not found / soft-deleted |
| POST | `/patients` | 201 created record | 422 validation (field-level details), 400 bad JSON |
| PUT | `/patients/{id}` | 200 updated | 404, 422; partial body allowed (all fields Optional) |
| DELETE | `/patients/{id}` | 200 `{patient_id, deleted_at}` | 404 |
| GET | `/calls?patient_id=` | 200 array | |
| GET | `/calls/{id}` | 200 | 404 |
| POST | `/vapi/webhook` | 200 Vapi result envelope | 401 if `x-vapi-secret` header mismatch |
| GET | `/dashboard` | HTML | |
| GET | `/docs` | Swagger (FastAPI default) — put in README as proof of API | |

Rules:
- Filters are case-insensitive; `last_name` uses `ILIKE`; `phone_number` and `date_of_birth` normalized before compare.
- Every 422 includes `details: [{field, message}]` so the voice agent can re-prompt the exact field.
- Global exception handler maps unhandled errors to 500 envelope (never a raw stack trace).
- Input sanitization: strip whitespace, reject control characters, length caps, parameterized queries via ORM.
- Security: no keys in code; webhook protected by shared secret; CORS limited to dashboard origin (same origin).

---

## 6. Voice agent design (Vapi)

### 6.1 Assistant config (`vapi/assistant.json`)
- `firstMessage`: "Hi, thanks for calling CareCloud. I'm the registration assistant and I can get you set up as a new patient in a couple of minutes. To start, could I get your first and last name?"
- `model`: `{provider: "openai", model: "gpt-4o-mini", temperature: 0.3, messages:[{role:"system", content: <system_prompt.md>}], tools: [...]}`
- `transcriber`: Deepgram `nova-3`, language `en` (switch to `multi` for Spanish bonus)
- `voice`: Vapi/11Labs natural female or male voice
- `serverUrl`: `https://<app>/vapi/webhook`, `serverUrlSecret`: `VAPI_SECRET`
- `serverMessages`: `["tool-calls", "end-of-call-report"]`
- `endCallFunctionEnabled: true`, `silenceTimeoutSeconds: 30`, `maxDurationSeconds: 900`
- `backgroundDenoisingEnabled: true`, `recordingEnabled: true` (transcript bonus)

### 6.2 Tools (all hit `/vapi/webhook`, dispatched by `toolCall.function.name`)

| Tool | Params | Returns | Purpose |
|---|---|---|---|
| `lookup_patient_by_phone` | `phone_number` | `{found, patient_id, first_name, last_name}` or `{found:false}` | Duplicate detection (bonus) — call right after phone is collected |
| `validate_field` | `field`, `value` | `{valid, normalized_value, error}` | Lets the agent re-prompt specific fields (DOB in future, 3-digit phone, bad state, bad zip) before the read-back |
| `save_patient` | all patient fields | `{success, patient_id, first_name}` or `{success:false, errors:[{field,message}]}` | Called only after caller confirms the read-back; runs the same `services.create_patient` as POST /patients |
| `update_patient` | `patient_id` + partial fields | same shape | Used when returning caller chooses "update" |
| `schedule_appointment` (bonus, mock) | `patient_id`, `preferred_day`, `preferred_time` | `{success, appointment_time}` | Returns a fake slot; stored in call summary only |

Tool results are returned to Vapi as `{"results":[{"toolCallId": id, "result": "<json string>"}]}`.
Every tool is idempotent and wrapped in try/except so a DB failure returns `{success:false, error:"..."}` and
the prompt instructs the agent to apologize and offer to retry or have staff call back — never silence.

### 6.3 System prompt (`vapi/system_prompt.md`) — key sections
1. **Role & tone**: human intake coordinator, warm, brief, one question at a time, never robotic lists.
2. **Collection order** (required first): name -> DOB -> sex -> phone (then `lookup_patient_by_phone`) -> street address -> city/state/zip -> email (optional, offer once).
3. **Then the opt-in line** verbatim from the PDF: "I can also collect your insurance information, emergency contact, and preferred language. Would you like to provide any of those?"
4. **Spelling & numbers**: ask the caller to spell unusual names; read phone/zip back digit by digit; accept "D-A-V-I-S" style corrections and replace the earlier value.
5. **Out-of-order answers**: if caller volunteers several fields at once, capture all, acknowledge, and continue with the next missing field.
6. **Validation loop**: call `validate_field` for DOB, phone, state, zip, email; if invalid, say what was wrong in plain words and re-ask only that field.
7. **Read-back & confirm**: summarize every collected field in natural sentences, ask "Is everything correct, or would you like to change anything?"; handle "change X" and re-confirm only the changed field.
8. **Save**: call `save_patient` only after an explicit yes. On success: "You're all set, {first_name}." + bonus appointment offer + goodbye + `endCall`. On failure: apologize, offer retry once, then offer staff callback; never say nothing.
9. **Start over**: if caller says "start over" / "let's restart", confirm, clear state, go back to name.
10. **Returning caller**: if lookup finds a match: "It looks like we already have a record for {First} {Last}. Would you like to update your information instead?" -> update flow via `update_patient`.
11. **Spanish** (bonus): if caller says "Hablo español" switch language for the remainder.
12. **Guardrails**: no medical advice, no PHI beyond the form, don't make up fields, don't ask for SSN, keep answers under two sentences.

The prompt file has inline comments (`<!-- why -->`) explaining each design choice, since "prompt engineering
thoughtful and documented" is graded.

### 6.4 Conversation state
Vapi keeps the conversation in the LLM context, so no server-side session store is needed. The server is
stateless; each tool call carries all needed fields. Dropped call = nothing saved unless the caller already
confirmed (save is atomic). The end-of-call-report webhook still logs the transcript and partial payload.

---

## 7. Edge cases checklist (graded 20%)

| Scenario | Handling |
|---|---|
| Future DOB / impossible date (02/30) | `validate_field` -> re-prompt DOB only |
| 3-digit or 11+ digit phone | normalize (strip leading 1), require exactly 10 -> re-prompt |
| Spelled corrections ("D-A-V-I-S") | prompt rule: letters spoken individually override prior spelling |
| Caller gives several fields at once | prompt rule: capture all, continue with next missing |
| Interruptions | Vapi barge-in handles audio; prompt says to answer the interruption then resume |
| "Start over" | prompt rule 9 |
| DB write fails | tool returns `success:false`; agent apologizes, retries once, offers callback; error logged |
| Telephony drops mid-call | no partial record saved; end-of-call-report logs transcript + partial payload for staff |
| Webhook unreachable / slow | Vapi tool timeout -> agent told "system is slow, let me try again" via prompt; server logs |
| Duplicate phone | lookup -> offer update |
| Bad webhook secret | 401, nothing processed |
| Invalid UUID in path | 400 envelope |
| Second call after restart | Postgres persistence; verified in test plan |

---

## 8. Observability
- Structured JSON logs to stdout via `logging` (Railway captures them): every tool call (name + args + result), every save (final payload), every end-of-call-report (call id, duration, ended reason, summary).
- Final collected payload also persisted in `call_logs.collected_payload`.
- Optional `LOG_TO_FILE=1` mirrors to `logs/conversations.log`.

---

## 9. Dashboard (`/dashboard`)
Single HTML file: table of patients (name, DOB, sex, phone, city/state, created_at), search box wired to
`GET /patients?last_name=`, row click opens a detail panel with all fields and linked call transcripts from
`GET /calls?patient_id=`, soft-delete button calling `DELETE`. Auto-refresh every 15 s. No auth (documented
limitation; could add basic auth header in 10 minutes).

---

## 10. Environment variables (`.env.example`)

```
DATABASE_URL=sqlite:///./patients.db          # Railway: postgresql+psycopg://...
VAPI_API_KEY=                                  # used only by vapi/push_assistant.py
VAPI_SECRET=change-me                          # must match assistant.serverUrlSecret
PUBLIC_BASE_URL=https://<app>.up.railway.app   # used by push_assistant.py to set serverUrl
OPENAI_API_KEY=                                # optional: only if bringing your own key to Vapi
SEED_DATA=true
LOG_LEVEL=INFO
LOG_TO_FILE=0
```

---

## 11. Accounts and prerequisites (do before the clock starts)
1. GitHub repo created (private is fine; add reviewer emails as collaborators later).
2. Vapi account (vapi.ai) — trial credits, buy/claim a **free US number** in Phone Numbers.
3. Railway account linked to GitHub; Postgres plugin available.
4. OpenAI key only if Vapi trial credits run out (Vapi bundles LLM usage otherwise).
5. Local: Python 3.12, `pip`, `ngrok` for local webhook testing.

---

## 12. Implementation timeline (3 h, strict)

| Time | Task | Done when |
|---|---|---|
| 0:00–0:15 | Scaffold repo, `config.py`, `db.py`, `models.py`, `seed.py`, `/health` | `uvicorn` boots, SQLite file created, seed rows present |
| 0:15–0:45 | `schemas.py` + `validation.py` + `services/patients.py` + `routers/patients.py` | All 5 endpoints pass manual curl; envelope + 422 details correct |
| 0:45–0:55 | `tests/` for API + validation | `pytest` green |
| 0:55–1:05 | Deploy to Railway with Postgres, set env vars | `/health` and `/docs` live on public URL |
| 1:05–1:35 | `routers/vapi.py` webhook: tool dispatch + end-of-call-report + `call_logs` | Simulated tool-call JSON via curl returns proper result |
| 1:35–2:00 | `system_prompt.md`, `assistant.json`, `push_assistant.py`; attach phone number | Test call from own phone completes a registration |
| 2:00–2:25 | Iterate on prompt from real calls: corrections, read-back, invalid DOB, start over, duplicate | Each edge case verified by a call |
| 2:25–2:40 | `dashboard.html` | Shows seed + registered patients, transcripts |
| 2:40–2:55 | README (setup, architecture, stack justification, env vars, limitations, next steps, prompt link, phone + URLs) | Another engineer could run it |
| 2:55–3:00 | Final call test, second call persistence check, push, send email | Submitted |

If behind schedule, cut in this order: appointment bonus -> Spanish -> dashboard polish -> tests. Never cut
read-back/confirm, validation, or persistence.

---

## 13. Test plan before submitting
1. `pytest` green.
2. `POST /patients` with bad DOB (future), bad phone, bad state -> 422 with field details.
3. `GET /patients?last_name=doe` returns seed Jane Doe. `DELETE` then `GET /patients/{id}` -> 404.
4. Call 1: register "Jane Davies", correct spelling to "Davis" mid-call, give a 3-digit phone first, then a real one, confirm, hear "You're all set, Jane."
5. `GET /patients?last_name=Davis` shows the record; dashboard shows it; `/calls` shows transcript.
6. Restart the Railway service; repeat query -> still there.
7. Call 2 from the same phone number as a saved record -> hears the duplicate prompt, chooses update, changes city, saved via `update_patient`.
8. Call 3: say "start over" midway -> restarts cleanly. Say "Hablo español" -> switches.
9. Temporarily set a bad `DATABASE_URL` -> call -> agent gives the graceful error, not silence. Revert.

---

## 14. Known limitations / Next Steps (for README)
- No auth on API/dashboard (add API key header or Cognito).
- No PHI encryption at rest beyond Railway defaults; not HIPAA (explicitly out of scope).
- Vapi hosted LLM loop; a custom-LLM endpoint (Claude) would allow stricter state machine control.
- Address not geocoded/validated (could add USPS/Smarty).
- Appointment scheduling is mocked; would integrate with a calendar service.
- Single-region deploy, no rate limiting, no retries/queue for webhook writes.

---

## 15. Submission email template

Subject: Voice AI Agent Assessment — Submission — Obaid Ullah

- Repository: <github url> (reviewers added)
- Phone number: +1 (XXX) XXX-XXXX
- API base URL: https://<app>.up.railway.app  (Swagger at /docs)
- Dashboard: https://<app>.up.railway.app/dashboard
- Notes: no credentials required; seed patients Jane Doe (201-555-0123) and Carlos Rivera; try calling from
  201-555-0123 spoofing is not needed — say that phone number during the call to trigger duplicate detection.
  Transcripts at /calls. Prompt at vapi/system_prompt.md.
