# Live deployment (for reviewers)

| Item | Value |
|---|---|
| **Phone number to call** | **+1 (732) 813-8172** |
| **API base URL** | https://api-production-686e1.up.railway.app |
| Swagger / OpenAPI | https://api-production-686e1.up.railway.app/docs |
| **Dashboard** | https://api-production-686e1.up.railway.app/dashboard |
| Call transcripts | https://api-production-686e1.up.railway.app/calls |
| Health | https://api-production-686e1.up.railway.app/health |
| Repository | https://github.com/obaidkhan009/carecloud-voice-agent |

## Testing notes

- No credentials are required for the API or dashboard.
- Seed patients: **Jane Doe** (phone 201-555-0123, DOB 03/14/1985) and **Carlos Rivera** (phone 732-555-0147).
- To see duplicate detection, give **201-555-0123** as your phone number during a call. The agent will offer to update Jane Doe's record instead of creating a new one.
- Try a correction mid-call ("actually it's spelled D-A-V-I-S"), an invalid date of birth (a future year), a 7-digit phone number, or "let's start over".
- After hanging up, the new patient appears on the dashboard within seconds, and the transcript is under `/calls` and in the patient's detail panel.
- Hosting: Railway (API + PostgreSQL). Voice: Vapi free U.S. number, Deepgram nova-3, OpenAI gpt-4o-mini, Vapi "Clara" voice.

Quick API checks:
```bash
API=https://api-production-686e1.up.railway.app
curl "$API/patients?last_name=doe"
curl -X POST "$API/patients" -H 'content-type: application/json' -d '{"first_name":"Sam","last_name":"Lee","date_of_birth":"05/06/1991","sex":"Male","phone_number":"9085550199","address_line_1":"9 Pine St","city":"Edison","state":"NJ","zip_code":"08817"}'
curl -X POST "$API/patients" -H 'content-type: application/json' -d '{"first_name":"Sam","date_of_birth":"01/01/2099"}'   # 422 with field-level details
```
