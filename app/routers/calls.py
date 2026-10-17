"""Read-only access to call transcripts (bonus: call recording/transcript linked to the patient)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import CallLogOut, envelope
from app.services import calls as svc

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("")
def list_calls(patient_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500),
               db: Session = Depends(get_db)):
    pid = None
    if patient_id:
        try:
            pid = uuid.UUID(patient_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="patient_id must be a valid UUID")
    rows = svc.list_calls(db, pid, limit)
    return envelope([CallLogOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_db)):
    try:
        cid = uuid.UUID(call_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="call_id must be a valid UUID")
    row = svc.get_call(db, cid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    return envelope(CallLogOut.model_validate(row).model_dump(mode="json"))
