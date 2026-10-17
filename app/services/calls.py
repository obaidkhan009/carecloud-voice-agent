"""Call-log persistence: links each Vapi call to the patient it created/updated and stores the transcript."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CallLog

log = logging.getLogger("services.calls")


def get_or_create(db: Session, vapi_call_id: str, caller_number: str | None = None) -> CallLog:
    row = db.scalar(select(CallLog).where(CallLog.vapi_call_id == vapi_call_id))
    if row is None:
        row = CallLog(vapi_call_id=vapi_call_id, caller_number=caller_number)
        db.add(row)
        db.flush()
    elif caller_number and not row.caller_number:
        row.caller_number = caller_number
    return row


def attach_patient(db: Session, vapi_call_id: str, patient_id: uuid.UUID, payload: dict, caller_number=None) -> None:
    row = get_or_create(db, vapi_call_id, caller_number)
    row.patient_id = patient_id
    row.collected_payload = payload
    db.commit()


def attach_appointment(db: Session, vapi_call_id: str, appointment: dict) -> None:
    row = get_or_create(db, vapi_call_id)
    row.appointment = appointment
    db.commit()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def finalize(db: Session, message: dict) -> CallLog:
    """Store Vapi's end-of-call-report (transcript, summary, timings)."""
    call = message.get("call") or {}
    artifact = message.get("artifact") or {}
    row = get_or_create(db, call.get("id") or message.get("callId") or "unknown",
                        (message.get("customer") or call.get("customer") or {}).get("number"))
    row.transcript = artifact.get("transcript") or message.get("transcript")
    row.summary = (message.get("analysis") or {}).get("summary") or message.get("summary")
    row.ended_reason = message.get("endedReason")
    row.started_at = _parse_ts(message.get("startedAt"))
    row.ended_at = _parse_ts(message.get("endedAt"))
    if row.collected_payload is None:
        # Dropped mid-call: keep whatever structured data Vapi extracted so staff can follow up.
        row.collected_payload = (message.get("analysis") or {}).get("structuredData")
    db.commit()
    db.refresh(row)
    log.info("call_finalized", extra={"payload": {
        "vapi_call_id": row.vapi_call_id, "patient_id": str(row.patient_id) if row.patient_id else None,
        "ended_reason": row.ended_reason, "summary": row.summary,
    }})
    return row


def list_calls(db: Session, patient_id: uuid.UUID | None = None, limit: int = 100) -> list[CallLog]:
    stmt = select(CallLog)
    if patient_id:
        stmt = stmt.where(CallLog.patient_id == patient_id)
    return list(db.scalars(stmt.order_by(CallLog.created_at.desc()).limit(limit)))


def get_call(db: Session, call_id: uuid.UUID) -> CallLog | None:
    return db.get(CallLog, call_id)
