# CareCloud Voice AI — Patient Registration Agent

A voice agent on a real U.S. phone number that registers new patients through natural conversation,
validates and persists their demographics to PostgreSQL, and exposes them through a REST API and a web dashboard.

| Deliverable | Value |
|---|---|
| Phone number | **+1 (732) 813-8172** |
| API base URL | https://api-production-686e1.up.railway.app — Swagger at `/docs` |
| Dashboard | https://api-production-686e1.up.railway.app/dashboard |
| Repository | https://github.com/obaidkhan009/carecloud-voice-agent |
| Credentials | None needed. Seed patients: Jane Doe (201-555-0123), Carlos Rivera (732-555-0147). |

> Say the phone number **201-555-0123** during a call to trigger the returning-caller / duplicate-detection flow.

---

## Architecture

```
 Caller ──PSTN──▶ Vapi (free U.S. number · Deepgram STT · Vapi TTS · gpt-4o-mini tool loop)
                      │
                      │  HTTPS POST /vapi/webhook   (x-vapi-secret header)
                      ▼
          FastAPI on Railway ────────────────────────────────────────────┐
          ├── routers/vapi.py      tool-calls ─▶ services/patients.py ──▶ PostgreSQL (Railway)
          │                        end-of-call-report ─▶ services/calls.py        │
          ├── routers/patients.py  GET/POST/PUT/DELETE /patients ─▶ same services ┘
          ├── routers/calls.py     GET /calls  (transcripts linked to patients)
          └── static/dashboard.html  GET /dashboard
```

**Separation of concerns**

| Layer | Where | Notes |
|---|---|---|
| Telephony / STT / TTS / barge-in | Vapi | Configured entirely from `vapi/assistant.template.json` and pushed with a script; nothing hand-clicked. |
| LLM behaviour | `vapi/system_prompt.md` + `vapi/tools.json` | Prompt is commented inline; comments are stripped before upload. |
| Validation | `app/validation.py` + `app/schemas.py` | One set of normalizers used by the API **and** the voice tools. Speech-friendly: accepts "two zero one …", spelled names, state names, 9-digit ZIPs. |
| Persistence | `app/models.py`, `app/services/` | SQLAlchemy 2, CHECK constraints in the DB, soft delete, UTC timestamps, call logs. |
| API | `app/routers/` | Thin; every response is `{ "data": …, "error": null }`. |

The voice agent never talks to the database directly: each tool call lands in `routers/vapi.py`, which calls the
**same service functions** as the REST endpoints, so validation and persistence rules are enforced once, server-side.

## Tech stack and why

| Choice | Reason |
|---|---|
| **Vapi** for telephony + voice | Free, real U.S. number in one API call; handles interruptions, endpointing and latency so the 3 hours go into the conversation and the data layer. Alternatives (Twilio + Deepgram + ElevenLabs media streams) would have cost most of the time budget on plumbing. |
| **OpenAI gpt-4o-mini** | Fast, cheap, reliable function calling; good enough for form-filling dialogue. Swapping to Claude or GPT-4o is one line in `assistant.template.json`. |
| **FastAPI + Pydantic v2 + SQLAlchemy 2** | Server-side validation with field-level 422 errors for free, OpenAPI docs at `/docs`, and a service layer that both the API and the webhook share. |
| **PostgreSQL (Railway)** in prod, **SQLite** locally/tests | One `DATABASE_URL` switches engines. Postgres survives redeploys; SQLite keeps tests at 0.3 s. |
| **Railway** | Public HTTPS URL for the webhook, Postgres add-on, logs in one place. |
| **Vanilla HTML dashboard** | One file, no build step, served by the same app. |

## Conversation design (summary; the full prompt is in `vapi/system_prompt.md`)

1. Greets, collects required fields one question at a time: name → DOB → sex → phone → address → city/state/ZIP.
2. Calls `lookup_patient_by_phone` as soon as the phone is known. If a record exists: *"It looks like we already have a record for Jane Doe. Would you like to update your information instead?"*
3. Calls `validate_field` after DOB, phone, state, ZIP, email; re-prompts **only** the failing field with a plain-English reason (future DOB, 7-digit phone, unknown state…).
4. Offers optional fields with the exact wording from the brief (insurance, emergency contact, preferred language), caller opts in.
5. Reads everything back in natural sentences and asks for confirmation; handles "actually it's D-A-V-I-S" by replacing the earlier value and re-confirming just that field.
6. Only after an explicit yes calls `save_patient` (or `update_patient`). Success → *"You're all set, Jane."* → optional mock appointment → goodbye → `endCall`.
7. Failure → apologizes, retries once, then promises a staff callback. Never silence, never a false "saved".
8. "Start over" resets the form; "Hablo español" switches language; interruptions are handled by Vapi barge-in plus a prompt rule to answer then resume.

Tools exposed to the model (`vapi/tools.json`): `lookup_patient_by_phone`, `validate_field`, `save_patient`,
`update_patient`, `get_patient`, `schedule_appointment` (mock), `endCall`.

## Data model

`patients` (see `app/models.py`): all fields from the brief with DB-level constraints — name lengths, `date_of_birth <= CURRENT_DATE`,
`sex IN (...)`, 10-digit phone, 2-letter state — plus `created_at` / `updated_at` (UTC, auto) and `deleted_at` for soft delete.
Indexes on `phone_number`, `last_name`, `date_of_birth` for the list filters.

`call_logs`: one row per Vapi call — `vapi_call_id`, `patient_id` (FK), caller number, start/end, `ended_reason`,
`transcript`, `summary`, `collected_payload` (final data the agent saved) and `appointment` (mock booking).

## REST API

All responses: `{"data": ..., "error": null}` or `{"data": null, "error": {"code", "message", "details"}}`.

| Method | Path | Status | Notes |
|---|---|---|---|
| GET | `/patients?last_name=&date_of_birth=&phone_number=&limit=&offset=` | 200 | Filters are case-insensitive / normalized |
| GET | `/patients/{id}` | 200 / 400 / 404 | 400 for a non-UUID, 404 for missing or soft-deleted |
| POST | `/patients` | 201 / 422 | Field-level `details` on validation errors |
| PUT | `/patients/{id}` | 200 / 400 / 404 / 422 | Partial updates; empty body → 400 |
| DELETE | `/patients/{id}` | 200 / 404 | Soft delete (`deleted_at`) |
| GET | `/calls?patient_id=` , `/calls/{id}` | 200 | Transcripts and summaries |
| POST | `/vapi/webhook` | 200 / 401 | Vapi only; requires `x-vapi-secret` |
| GET | `/health`, `/docs`, `/dashboard` | 200 | |

Example:
```bash
curl -X POST "$API/patients" -H 'content-type: application/json' -d '{
  "first_name":"Jane","last_name":"Davis","date_of_birth":"03/14/1985","sex":"Female",
  "phone_number":"(908) 555-0100","address_line_1":"5 Oak Ave","city":"Somerset","state":"New Jersey","zip_code":"08873"}'
```

## Running locally

```bash
git clone https://github.com/obaidkhan009/carecloud-voice-agent && cd carecloud-voice-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # defaults to SQLite, seeds 2 patients
.venv/bin/uvicorn app.main:app --reload   # http://localhost:8000/docs  /dashboard
.venv/bin/pytest -q                       # 18 tests: validation, API, webhook
```

To test the phone flow against a local server: `ngrok http 8000`, set `PUBLIC_BASE_URL` to the ngrok URL and run
`python vapi/push_assistant.py` (see `docs/VAPI_SETUP.md`).

## Deploying (Railway)

```bash
railway login && railway init             # new project
railway add --database postgres           # DATABASE_URL is injected automatically
railway variables --set VAPI_SECRET=<random> --set SEED_DATA=true --set APP_ENV=production
railway up && railway domain              # prints the public URL
```
Then push the assistant + claim the number: `python vapi/push_assistant.py --number` (`docs/VAPI_SETUP.md`).

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | API | `sqlite:///./patients.db` locally; Railway injects `postgresql://…` (driver prefix added automatically) |
| `VAPI_SECRET` | API + script | Shared secret; the webhook rejects requests whose `x-vapi-secret` doesn't match |
| `SEED_DATA` | API | Insert 2 demo patients on first boot (default true) |
| `LOG_LEVEL`, `LOG_TO_FILE` | API | JSON logs to stdout; optionally also `logs/conversations.log` |
| `VAPI_API_KEY`, `PUBLIC_BASE_URL`, `VAPI_ASSISTANT_ID` | `vapi/push_assistant.py` only | Create/update the assistant and claim the number. Never needed by the running API. |

No key is hardcoded anywhere; `.env` is git-ignored.

## Observability

Every tool call, tool result, saved payload, and end-of-call report is logged as one JSON line to stdout
(`railway logs`), e.g. `{"event":"tool_result","payload":{"call_id":"…","tool":"save_patient","result":{…}}}`.
Final collected data is also stored in `call_logs.collected_payload` and visible on the dashboard per patient.

## Edge cases and resilience

| Situation | Behaviour |
|---|---|
| Invalid DOB (future, Feb 30, 2-digit year) | `validate_field` returns a spoken reason; agent re-asks only the DOB |
| 3-digit / 11-digit / "555" phone | normalized (leading 1 stripped), NANP check, re-prompt with the digit count heard |
| Spelled correction ("D-A-V-I-S") | normalizer collapses spelled letters; prompt rule makes the spelling authoritative |
| Several answers at once / out of order | prompt captures all, continues with the next missing field |
| Interruptions | Vapi barge-in (`stopSpeakingPlan`) + prompt rule: answer, then resume |
| "Start over" | prompt resets state, restarts at name; nothing was written yet |
| DB write fails | tool returns `success:false`; agent apologizes, retries once, offers callback; stack trace logged |
| Webhook secret wrong | 401, nothing processed |
| Telephony drops mid-call | nothing partial is saved; end-of-call report still logs transcript + Vapi's structured extraction for staff follow-up |
| Same phone as an existing record | duplicate detection before and at save time; update flow or explicit `create_duplicate` |
| Server restart | Postgres persistence verified (register on call 1, query after redeploy) |

## Bonus items implemented

- Duplicate detection / update instead of create.
- Mock appointment scheduling after registration (stored on the call log).
- Spanish switch on "Hablo español" (Deepgram `multi` transcriber).
- Transcript + summary per call linked to the patient (`/calls`, dashboard).
- Dashboard at `/dashboard` with search, detail view, call transcripts, soft delete.
- 18 automated tests (`pytest`).

## Known limitations / trade-offs

- **No auth** on the API or dashboard (out of scope for the brief; an API-key header is a 10-line change).
- **Not HIPAA**: PHI is stored in plain Postgres; no encryption at rest beyond Railway's defaults, no audit log. Do not use real patient data.
- `Base.metadata.create_all` instead of Alembic migrations, deliberately, for a 3-hour build.
- The LLM loop runs inside Vapi (hosted). A custom-LLM endpoint would allow a strict state machine, at the cost of latency and time.
- Address is sanitized but not verified against USPS; appointment scheduling is mocked.
- Single region, no rate limiting, no retry queue for webhook writes.

## Next steps

API-key auth, Alembic migrations, USPS address validation, real scheduling integration, call recording storage,
LLM-as-judge regression tests on transcripts, and a stricter custom-LLM state machine if conversational drift shows up in review.
