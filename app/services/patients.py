"""Patient service layer. Used by BOTH the REST routers and the Vapi tool handlers, so every write
goes through the same validation and the same soft-delete rules."""
from __future__ import annotations

import logging
import uuid
from datetime import date, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import validation as v
from app.models import Patient, utcnow
from app.schemas import PatientCreate, PatientUpdate

log = logging.getLogger("services.patients")


class NotFoundError(Exception):
    pass


def _active(stmt):
    return stmt.where(Patient.deleted_at.is_(None))


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    log.info("patient_created", extra={"payload": {"patient_id": str(patient.patient_id), **_safe(data.model_dump())}})
    return patient


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.scalar(_active(select(Patient).where(Patient.patient_id == patient_id)))
    if patient is None:
        raise NotFoundError(f"Patient {patient_id} not found")
    return patient


def list_patients(
    db: Session,
    *,
    last_name: str | None = None,
    date_of_birth: str | date | None = None,
    phone_number: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    stmt = _active(select(Patient))
    if last_name:
        stmt = stmt.where(Patient.last_name.ilike(f"%{v.sanitize_text(last_name, 50)}%"))
    if date_of_birth:
        stmt = stmt.where(Patient.date_of_birth == v.parse_dob(date_of_birth))
    if phone_number:
        stmt = stmt.where(Patient.phone_number == v.normalize_phone(phone_number))
    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def find_by_phone(db: Session, phone_number: str) -> Patient | None:
    digits = v.normalize_phone(phone_number)
    return db.scalar(
        _active(select(Patient).where(Patient.phone_number == digits)).order_by(Patient.created_at.desc())
    )


def update_patient(db: Session, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
    patient = get_patient(db, patient_id)
    changes = data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(patient, key, value)
    patient.updated_at = utcnow()
    db.commit()
    db.refresh(patient)
    log.info("patient_updated", extra={"payload": {"patient_id": str(patient_id), **_safe(changes)}})
    return patient


def soft_delete_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = get_patient(db, patient_id)
    patient.deleted_at = utcnow()
    db.commit()
    db.refresh(patient)
    log.info("patient_deleted", extra={"payload": {"patient_id": str(patient_id)}})
    return patient


def _safe(d: dict) -> dict:
    return {k: (val.isoformat() if isinstance(val, date) else val) for k, val in d.items()}
