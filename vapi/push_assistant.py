"""Create or update the Vapi assistant and (optionally) claim a free U.S. phone number.

Usage (from repo root, with VAPI_API_KEY, PUBLIC_BASE_URL and VAPI_SECRET in .env or the environment):

    python vapi/push_assistant.py              # create/update assistant only
    python vapi/push_assistant.py --number     # ...and claim a free Vapi U.S. number attached to it
    python vapi/push_assistant.py --number --area-code 732

The assistant id and phone number id are cached in vapi/.state.json so re-running updates in place.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")

import os  # noqa: E402

API = "https://api.vapi.ai"
STATE_FILE = ROOT / ".state.json"


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_prompt() -> str:
    text = (ROOT / "system_prompt.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # strip engineer-facing comments
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_assistant(server_url: str, secret: str) -> dict:
    template = json.loads((ROOT / "assistant.template.json").read_text(encoding="utf-8"))
    tools = json.loads((ROOT / "tools.json").read_text(encoding="utf-8"))
    template["model"]["messages"][0]["content"] = load_prompt()
    template["model"]["tools"] = tools
    template["server"] = {"url": server_url, "secret": secret, "timeoutSeconds": 20}
    return template


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--number", action="store_true", help="claim a free Vapi US number and attach the assistant")
    ap.add_argument("--area-code", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print the assistant payload and exit")
    args = ap.parse_args()

    key = os.getenv("VAPI_API_KEY")
    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    secret = os.getenv("VAPI_SECRET") or ""
    if not base:
        die("PUBLIC_BASE_URL is required (e.g. https://your-app.up.railway.app)")
    payload = build_assistant(f"{base}/vapi/webhook", secret)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return
    if not key:
        die("VAPI_API_KEY is required")
    if not secret:
        die("VAPI_SECRET is required and must match the API's VAPI_SECRET env var")

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    assistant_id = os.getenv("VAPI_ASSISTANT_ID") or state.get("assistant_id")

    if assistant_id:
        r = requests.patch(f"{API}/assistant/{assistant_id}", headers=headers, json=payload, timeout=30)
        action = "updated"
    else:
        r = requests.post(f"{API}/assistant", headers=headers, json=payload, timeout=30)
        action = "created"
    if r.status_code >= 300:
        die(f"assistant {action[:-1]} failed: {r.status_code} {r.text}")
    assistant_id = r.json()["id"]
    state["assistant_id"] = assistant_id
    print(f"Assistant {action}: {assistant_id}")

    if args.number:
        number_id = state.get("phone_number_id")
        if number_id:
            r = requests.patch(f"{API}/phone-number/{number_id}", headers=headers,
                               json={"assistantId": assistant_id}, timeout=30)
        else:
            body = {"provider": "vapi", "assistantId": assistant_id, "name": "CareCloud Registration"}
            if args.area_code:
                body["numberDesiredAreaCode"] = args.area_code
            r = requests.post(f"{API}/phone-number", headers=headers, json=body, timeout=30)
        if r.status_code >= 300:
            die(f"phone number request failed: {r.status_code} {r.text}")
        data = r.json()
        state["phone_number_id"] = data["id"]
        state["phone_number"] = data.get("number")
        print(f"Phone number: {data.get('number')}  (id {data['id']})")

    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"State saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
