"""SQLAlchemy models. Constraints are enforced in the database as well as in Pydantic (defense in depth)."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False)  # normalized 10 digits
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    address_line_1: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)

    insurance_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insurance_member_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(50), nullable=False, default="English")
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    calls: Mapped[list["CallLog"]] = relationship(back_populates="patient")

    __table_args__ = (
        CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_first_name_len"),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_last_name_len"),
        CheckConstraint("date_of_birth <= CURRENT_DATE", name="ck_dob_not_future"),
        CheckConstraint(f"sex IN {SEX_VALUES}", name="ck_sex_enum"),
        CheckConstraint("length(phone_number) = 10", name="ck_phone_len"),
        CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_city_len"),
        CheckConstraint("length(state) = 2", name="ck_state_len"),
        Index("ix_patients_phone", "phone_number"),
        Index("ix_patients_last_name", "last_name"),
        Index("ix_patients_dob", "date_of_birth"),
    )


class CallLog(Base):
    """One row per phone call. Created when the agent first writes data, finalized by Vapi's end-of-call report."""

    __tablename__ = "call_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vapi_call_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.patient_id"), nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    appointment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    patient: Mapped[Patient | None] = relationship(back_populates="calls")
