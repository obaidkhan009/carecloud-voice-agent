"""REST API for patients. Thin layer: parse -> service -> envelope."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import PatientCreate, PatientOut, PatientUpdate, envelope
from app.services import patients as svc

router = APIRouter(prefix="/patients", tags=["patients"])


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="patient_id must be a valid UUID")


def _out(p) -> dict:
    return PatientOut.model_validate(p).model_dump(mode="json")


@router.get("")
def list_patients(
    last_name: str | None = Query(default=None, max_length=50),
    date_of_birth: str | None = Query(default=None, description="MM/DD/YYYY"),
    phone_number: str | None = Query(default=None, description="10-digit U.S. number"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    rows = svc.list_patients(
        db, last_name=last_name, date_of_birth=date_of_birth, phone_number=phone_number, limit=limit, offset=offset
    )
    return envelope([_out(p) for p in rows])


@router.get("/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    return envelope(_out(svc.get_patient(db, parse_uuid(patient_id))))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_patient(body: PatientCreate, db: Session = Depends(get_db)):
    return envelope(_out(svc.create_patient(db, body)))


@router.put("/{patient_id}")
def update_patient(patient_id: str, body: PatientUpdate, db: Session = Depends(get_db)):
    if not body.model_dump(exclude_unset=True):
        raise HTTPException(status_code=400, detail="Request body must include at least one field to update")
    return envelope(_out(svc.update_patient(db, parse_uuid(patient_id), body)))


@router.delete("/{patient_id}")
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    p = svc.soft_delete_patient(db, parse_uuid(patient_id))
    return envelope({"patient_id": str(p.patient_id), "deleted_at": _out(p)["deleted_at"]})
