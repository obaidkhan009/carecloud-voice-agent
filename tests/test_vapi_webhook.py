import json

from tests.conftest import VALID

H = {"x-vapi-secret": "test-secret"}


def tool_call(client, name, args, call_id="call-1"):
    body = {"message": {"type": "tool-calls", "call": {"id": call_id, "customer": {"number": "+12015550188"}},
                        "toolCallList": [{"id": "tc-1", "name": name, "arguments": args}]}}
    r = client.post("/vapi/webhook", json=body, headers=H)
    assert r.status_code == 200, r.text
    return json.loads(r.json()["results"][0]["result"])


def test_rejects_bad_secret(client):
    r = client.post("/vapi/webhook", json={"message": {"type": "tool-calls"}}, headers={"x-vapi-secret": "nope"})
    assert r.status_code == 401
    assert client.post("/vapi/webhook", json={"message": {"type": "tool-calls"}}).status_code == 401


def test_validate_field(client):
    assert tool_call(client, "validate_field", {"field": "date_of_birth", "value": "12/31/2099"})["valid"] is False
    ok = tool_call(client, "validate_field", {"field": "phone_number", "value": "201 555 0199"})
    assert ok["valid"] and ok["normalized_value"] == "2015550199" and ok["spoken"] == "(201) 555-0199"
    assert tool_call(client, "validate_field", {"field": "ssn", "value": "1"})["valid"] is False


def test_lookup_save_duplicate_update_flow(client):
    assert tool_call(client, "lookup_patient_by_phone", {"phone_number": "9085550000"})["found"] is False
    seed = tool_call(client, "lookup_patient_by_phone", {"phone_number": "201-555-0123"})
    assert seed["found"] and seed["first_name"] == "Jane" and seed["last_name"] == "Doe"

    res = tool_call(client, "save_patient", {**VALID, "phone_number": "9085550000"})
    assert res["success"] and res["message"].startswith("Saved. You're all set, Jane")
    pid = res["patient_id"]

    dup = tool_call(client, "save_patient", {**VALID, "phone_number": "9085550000"})
    assert dup["success"] is False and dup["duplicate"] and dup["patient_id"] == pid

    forced = tool_call(client, "save_patient", {**VALID, "phone_number": "9085550000", "create_duplicate": True})
    assert forced["success"] and forced["patient_id"] != pid

    upd = tool_call(client, "update_patient", {"patient_id": pid, "city": "Edison", "state": "new jersey"}, call_id="call-2")
    assert upd["success"] and upd["updated_fields"] == ["city", "state"]
    assert client.get(f"/patients/{pid}").json()["data"]["city"] == "Edison"

    bad = tool_call(client, "save_patient", {**VALID, "phone_number": "12"})
    assert bad["success"] is False and bad["errors"][0]["field"] == "phone_number"

    missing = tool_call(client, "save_patient", {"first_name": "A"})
    assert missing["success"] is False and any(e["field"] == "last_name" for e in missing["errors"])

    assert tool_call(client, "update_patient", {"patient_id": "nope", "city": "X"})["success"] is False
    assert tool_call(client, "no_such_tool", {})["success"] is False

    appt = tool_call(client, "schedule_appointment", {"patient_id": pid, "preferred_day": "tuesday", "preferred_time": "afternoon"})
    assert appt["success"] and "Tuesday" in appt["spoken"]


def test_end_of_call_report_links_transcript(client):
    res = tool_call(client, "save_patient", {**VALID, "phone_number": "9085550001"}, call_id="call-9")
    report = {"message": {"type": "end-of-call-report", "call": {"id": "call-9"}, "endedReason": "customer-ended-call",
                          "startedAt": "2026-10-17T10:00:00Z", "endedAt": "2026-10-17T10:04:00Z",
                          "artifact": {"transcript": "AI: Hi...\nUser: Jane Davis"},
                          "analysis": {"summary": "Registered Jane Davis."}}}
    r = client.post("/vapi/webhook", json=report, headers=H)
    assert r.status_code == 200
    calls = client.get(f"/calls?patient_id={res['patient_id']}").json()["data"]
    assert len(calls) == 1
    assert calls[0]["transcript"].startswith("AI:") and calls[0]["summary"] == "Registered Jane Davis."
    assert calls[0]["collected_payload"]["first_name"] == "Jane"
    assert client.get(f"/calls/{calls[0]['id']}").status_code == 200


def test_other_events_acknowledged(client):
    r = client.post("/vapi/webhook", json={"message": {"type": "status-update", "status": "ended"}}, headers=H)
    assert r.status_code == 200 and r.json()["ok"]
