# Vapi setup: assistant + free U.S. phone number (about 10 minutes)

Vapi gives every account trial credits and lets you claim **free U.S. phone numbers** (provider "vapi",
no Twilio account needed). The number is real and dialable from any U.S. phone.

## 1. Create the account and API key
1. Go to https://dashboard.vapi.ai and sign up (Google login is fine).
2. Left sidebar -> **Organization Settings -> API Keys** (or the key icon). Copy the **Private** API key.
3. On your machine, add it to `.env` in the repo root:
   ```
   VAPI_API_KEY=<private key>
   VAPI_SECRET=<any long random string, same value as the VAPI_SECRET set on Railway>
   PUBLIC_BASE_URL=https://<your-railway-domain>
   ```
   Generate a secret with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

## 2. Push the assistant and claim the number (one command)
```
cd carecloud-voice-agent
.venv/bin/python vapi/push_assistant.py --number --area-code 732
```
What it does:
- Reads `vapi/system_prompt.md` (strips the HTML comments), `vapi/tools.json` and `vapi/assistant.template.json`.
- Creates the assistant via `POST https://api.vapi.ai/assistant` (or updates it if `vapi/.state.json` already has an id).
- Claims a free number via `POST https://api.vapi.ai/phone-number` with `{"provider": "vapi"}` and attaches the assistant.
- Prints the phone number and saves ids to `vapi/.state.json` (git-ignored).

Re-run without `--number` whenever you edit the prompt or tools; it updates the assistant in place.

## 2b. Doing the same in the dashboard instead (if you prefer clicking)
1. **Assistants -> Create Assistant -> Blank**. Name it "CareCloud Patient Registration".
2. Model tab: provider OpenAI, model gpt-4o-mini, temperature 0.3. Paste the contents of `vapi/system_prompt.md`
   (without the `<!-- -->` comment blocks) into the System Prompt. First message: copy from `vapi/assistant.template.json`.
3. Tools tab: create each function from `vapi/tools.json` (name, description, parameters). For every tool set
   **Server URL** = `https://<railway-domain>/vapi/webhook`. Also add the built-in **End Call** tool.
4. Advanced tab: Server URL = `https://<railway-domain>/vapi/webhook`, Server URL Secret = your `VAPI_SECRET`,
   Server Messages = `tool-calls`, `end-of-call-report`. Transcriber: Deepgram nova-3, language `multi`. Voice: Vapi "Clara" (version 2, language auto).
5. **Phone Numbers -> Create Phone Number -> Free Vapi Number**, pick an area code, then under *Inbound Settings*
   choose the assistant. The number shown is the one to send to CareCloud.

## 3. Verify
- Call the number from any phone. You should hear "Hi, thanks for calling CareCloud..."
- Watch Railway logs: `railway logs` shows `tool_call` / `tool_result` JSON lines for each step.
- After hanging up, `GET /calls` on the API shows the transcript, and `/dashboard` shows the patient.

## Notes / limits
- Free Vapi numbers can receive inbound calls from U.S. numbers; outbound and international are restricted. That is all this challenge needs.
- Trial credits cover well over an hour of calls. If the dashboard shows "insufficient credits", add a card under Billing; a 5-minute call costs a few cents.
- If number claiming fails with a quota error, delete unused numbers in the dashboard (free numbers are limited per account) or use a Twilio trial number imported into Vapi (**Phone Numbers -> Import Twilio**).
