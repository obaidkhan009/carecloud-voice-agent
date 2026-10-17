"""Vapi server webhook.

Vapi POSTs here for every event we subscribe to (`serverMessages` in vapi/assistant.json):
  * `tool-calls`          -> the LLM decided to call one of our tools; we run it and return results.
  * `end-of-call-report`  -> transcript, summary and timings once the call ends.
Anything else is acknowledged with 200 and ignored.

Tool handlers call the same service layer as the REST API, so validation and persistence are identical.
Every handler is wrapped so a failure becomes a `{"success": false, "error": ...}` result the agent can
explain to the caller, never a 500 that would leave the caller in silence.
"""
from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import validation as v
from app.config import settings
from app.db import get_db
from app.schemas import PatientCreate, PatientOut, PatientUpdate, REQUIRED_FIELDS
from app.services import calls as calls_svc
from app.services import patients as patients_svc

router = APIRouter(prefix="/vapi", tags=["vapi"])
log = logging.getLogger("vapi")

PATIENT_FIELDS = set(v.NORMALIZERS.keys())


# ---------------------------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------------------------
def _validation_errors(exc: ValidationError) -> list[dict]:
    out = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "body"
        msg = err["msg"].replace("Value error, ", "")
        if err["type"] == "missing":
            msg = f"{field.replace('_', ' ')} is required."
        out.append({"field": field, "message": msg})
    return out


def _patient_summary(p) -> dict:
    d = PatientOut.model_validate(p).model_dump(mode="json")
    d["phone_number_spoken"] = v.format_phone(p.phone_number)
    return d


def tool_lookup_patient_by_phone(db: Session, args: dict, ctx: dict) -> dict:
    try:
        patient = patients_svc.find_by_phone(db, args.get("phone_number", ""))
    except v.FieldError as e:
        return {"found": False, "valid_phone": False, "error": e.message}
    if patient is None:
        return {"found": False, "valid_phone": True}
    return {
        "found": True,
        "valid_phone": True,
        "patient_id": str(patient.patient_id),
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "city": patient.city,
        "state": patient.state,
    }


def tool_validate_field(db: Session, args: dict, ctx: dict) -> dict:
    field = (args.get("field") or "").strip()
    value = args.get("value")
    try:
        normalized = v.validate_one(field, value)
    except v.FieldError as e:
        return {"valid": False, "field": field, "error": e.message}
    result = {"valid": True, "field": field, "normalized_value": normalized}
    if field in ("phone_number", "emergency_contact_phone") and normalized:
        result["spoken"] = v.format_phone(normalized)
    return result


def _patient_args(args: dict) -> dict:
    return {k: val for k, val in args.items() if k in PATIENT_FIELDS and val not in (None, "", "null")}


def tool_save_patient(db: Session, args: dict, ctx: dict) -> dict:
    data = _patient_args(args)
    try:
        body = PatientCreate(**data)
    except ValidationError as exc:
        errors = _validation_errors(exc)
        return {"success": False, "errors": errors,
                "message": "Some details need fixing: " + "; ".join(e["message"] for e in errors)}
    # Duplicate guard: don't create a second record for the same number without an explicit choice.
    existing = patients_svc.find_by_phone(db, body.phone_number)
    if existing and not args.get("create_duplicate"):
        return {
            "success": False, "duplicate": True, "patient_id": str(existing.patient_id),
            "first_name": existing.first_name, "last_name": existing.last_name,
            "message": f"A record for {existing.first_name} {existing.last_name} already uses this phone number. "
                       "Ask whether to update it (use update_patient) or create a new record (set create_duplicate=true).",
        }
    patient = patients_svc.create_patient(db, body)
    calls_svc.attach_patient(db, ctx["call_id"], patient.patient_id, _patient_summary(patient), ctx.get("caller_number"))
    return {"success": True, "patient_id": str(patient.patient_id), "first_name": patient.first_name,
            "message": f"Saved. You're all set, {patient.first_name}."}


def tool_update_patient(db: Session, args: dict, ctx: dict) -> dict:
    try:
        pid = uuid.UUID(str(args.get("patient_id", "")))
    except ValueError:
        return {"success": False, "error": "patient_id is missing or invalid. Call lookup_patient_by_phone first."}
    data = _patient_args(args)
    if not data:
        return {"success": False, "error": "No fields to update were provided."}
    try:
        body = PatientUpdate(**data)
    except ValidationError as exc:
        errors = _validation_errors(exc)
        return {"success": False, "errors": errors,
                "message": "Some details need fixing: " + "; ".join(e["message"] for e in errors)}
    try:
        patient = patients_svc.update_patient(db, pid, body)
    except patients_svc.NotFoundError:
        return {"success": False, "error": "That patient record no longer exists."}
    calls_svc.attach_patient(db, ctx["call_id"], patient.patient_id, _patient_summary(patient), ctx.get("caller_number"))
    return {"success": True, "patient_id": str(patient.patient_id), "first_name": patient.first_name,
            "updated_fields": sorted(data.keys()), "message": f"Updated. You're all set, {patient.first_name}."}


def tool_get_patient(db: Session, args: dict, ctx: dict) -> dict:
    try:
        patient = patients_svc.get_patient(db, uuid.UUID(str(args.get("patient_id", ""))))
    except (ValueError, patients_svc.NotFoundError):
        return {"found": False}
    return {"found": True, "patient": _patient_summary(patient)}


def tool_schedule_appointment(db: Session, args: dict, ctx: dict) -> dict:
    """Bonus: mock scheduling. Returns the next weekday slot matching the caller's preference."""
    preferred_day = (args.get("preferred_day") or "").lower()
    preferred_time = (args.get("preferred_time") or "morning").lower()
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    start = datetime.now() + timedelta(days=1)
    for i in range(14):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        if preferred_day and preferred_day in weekdays and weekdays[d.weekday()] != preferred_day:
            continue
        hour = 14 if "afternoon" in preferred_time else 9
        slot = d.replace(hour=hour, minute=30 if "afternoon" in preferred_time else 0, second=0, microsecond=0)
        appt = {
            "appointment_id": f"APT-{secrets.token_hex(3).upper()}",
            "patient_id": args.get("patient_id"),
            "datetime": slot.isoformat(timespec="minutes"),
            "spoken": slot.strftime("%A, %B %-d at %-I:%M %p"),
            "provider": "Dr. Patel (new patient visit)",
            "mock": True,
        }
        calls_svc.attach_appointment(db, ctx["call_id"], appt)
        return {"success": True, **appt}
    return {"success": False, "error": "No slots available in the next two weeks."}


TOOLS = {
    "lookup_patient_by_phone": tool_lookup_patient_by_phone,
    "validate_field": tool_validate_field,
    "save_patient": tool_save_patient,
    "update_patient": tool_update_patient,
    "get_patient": tool_get_patient,
    "schedule_appointment": tool_schedule_appointment,
}


# ---------------------------------------------------------------------------------------------
# Webhook entrypoint
# ---------------------------------------------------------------------------------------------
def _extract_tool_calls(message: dict) -> list[tuple[str, str, dict]]:
    """Vapi has shipped two shapes; accept both: toolCallList[{id,name,arguments}] and
    toolWithToolCallList[{toolCall:{id,function:{name,arguments}}}]."""
    calls = []
    for tc in message.get("toolCallList") or []:
        fn = tc.get("function") or {}
        name = tc.get("name") or fn.get("name")
        args = tc.get("arguments") if "arguments" in tc else fn.get("arguments")
        calls.append((tc.get("id"), name, args))
    if not calls:
        for item in message.get("toolWithToolCallList") or []:
            tc = item.get("toolCall") or {}
            fn = tc.get("function") or {}
            calls.append((tc.get("id"), fn.get("name"), fn.get("arguments")))
    out = []
    for cid, name, args in calls:
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {}
        out.append((cid, name, args or {}))
    return out


@router.post("/webhook")
async def vapi_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_vapi_secret: str | None = Header(default=None),
):
    if settings.vapi_secret and not secrets.compare_digest(x_vapi_secret or "", settings.vapi_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload: dict[str, Any] = await request.json()
    message = payload.get("message") or {}
    mtype = message.get("type")
    call = message.get("call") or {}
    ctx = {
        "call_id": call.get("id") or message.get("callId") or "unknown",
        "caller_number": (call.get("customer") or message.get("customer") or {}).get("number"),
    }

    if mtype == "tool-calls":
        results = []
        for tool_call_id, name, args in _extract_tool_calls(message):
            handler = TOOLS.get(name)
            log.info("tool_call", extra={"payload": {"call_id": ctx["call_id"], "tool": name, "args": args}})
            if handler is None:
                result = {"success": False, "error": f"Unknown tool '{name}'"}
            else:
                try:
                    result = handler(db, args, ctx)
                except Exception as exc:  # noqa: BLE001 - must never surface as silence to the caller
                    db.rollback()
                    log.exception("tool_failed", extra={"payload": {"call_id": ctx["call_id"], "tool": name}})
                    result = {"success": False, "error": "The registration system is temporarily unavailable. "
                                                         "Apologize, offer to try once more, then offer a staff callback."}
            log.info("tool_result", extra={"payload": {"call_id": ctx["call_id"], "tool": name, "result": result}})
            results.append({"toolCallId": tool_call_id, "result": json.dumps(result)})
        return {"results": results}

    if mtype == "end-of-call-report":
        row = calls_svc.finalize(db, message)
        return {"ok": True, "call_log_id": str(row.id)}

    # status-update, transcript, hang, speech-update, etc. are not needed; acknowledge and move on.
    log.debug("vapi_event_ignored", extra={"payload": {"type": mtype, "call_id": ctx["call_id"]}})
    return {"ok": True}
