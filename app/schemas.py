"""Pydantic request/response schemas. All server-side validation lives here + app/validation.py."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app import validation as v

SexLiteral = str  # validated by normalize_sex into one of validation.SEX_VALUES


class PatientBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str | None = Field(default=None, max_length=60, examples=["Jane"])
    last_name: str | None = Field(default=None, max_length=60, examples=["Doe"])
    date_of_birth: str | date | None = Field(default=None, examples=["03/14/1985"], description="MM/DD/YYYY")
    sex: str | None = Field(default=None, examples=["Female"], description="Male | Female | Other | Decline to Answer")
    phone_number: str | None = Field(default=None, examples=["2015550123"], description="10-digit U.S. number")
    email: str | None = Field(default=None, examples=["jane@example.com"])
    address_line_1: str | None = Field(default=None, max_length=200, examples=["12 Main St"])
    address_line_2: str | None = Field(default=None, max_length=200, examples=["Apt 4B"])
    city: str | None = Field(default=None, max_length=100, examples=["Somerset"])
    state: str | None = Field(default=None, examples=["NJ"])
    zip_code: str | None = Field(default=None, examples=["08873"])
    insurance_provider: str | None = Field(default=None, max_length=100)
    insurance_member_id: str | None = Field(default=None, max_length=60)
    preferred_language: str | None = Field(default=None, max_length=50)
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = Field(default=None)

    # --- field normalizers (raise ValueError -> 422 with a field-level message) ---
    @field_validator("first_name", "last_name")
    @classmethod
    def _names(cls, val, info):
        return None if val is None else v.normalize_name(val, info.field_name)

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, val):
        return None if val is None else v.parse_dob(val)

    @field_validator("sex")
    @classmethod
    def _sex(cls, val):
        return None if val is None else v.normalize_sex(val)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, val):
        return None if val is None else v.normalize_phone(val)

    @field_validator("email")
    @classmethod
    def _email(cls, val):
        return v.normalize_email(val)

    @field_validator("address_line_1")
    @classmethod
    def _addr1(cls, val):
        return None if val is None else v.required_text(val, "address_line_1", 200)

    @field_validator("address_line_2", "insurance_provider")
    @classmethod
    def _optional_text(cls, val):
        return v.sanitize_text(val, 200) or None

    @field_validator("city")
    @classmethod
    def _city(cls, val):
        return None if val is None else v.required_text(val, "city", 100)

    @field_validator("state")
    @classmethod
    def _state(cls, val):
        return None if val is None else v.normalize_state(val)

    @field_validator("zip_code")
    @classmethod
    def _zip(cls, val):
        return None if val is None else v.normalize_zip(val)

    @field_validator("insurance_member_id")
    @classmethod
    def _member(cls, val):
        return v.normalize_member_id(val)

    @field_validator("preferred_language")
    @classmethod
    def _lang(cls, val):
        return None if val is None else v.normalize_language(val)

    @field_validator("emergency_contact_name")
    @classmethod
    def _ec_name(cls, val):
        return None if not val else v.normalize_name(val, "emergency_contact_name")

    @field_validator("emergency_contact_phone")
    @classmethod
    def _ec_phone(cls, val):
        return None if not val else v.normalize_phone(val, "emergency_contact_phone")


REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)


class PatientCreate(PatientBase):
    """POST body. Required fields are enforced after normalization so the error message names the field."""

    first_name: str = Field(max_length=60)
    last_name: str = Field(max_length=60)
    date_of_birth: str | date
    sex: str
    phone_number: str
    address_line_1: str = Field(max_length=200)
    city: str = Field(max_length=100)
    state: str
    zip_code: str
    preferred_language: str | None = "English"


class PatientUpdate(PatientBase):
    """PUT body. Every field optional; only provided fields change."""


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @field_serializer("date_of_birth")
    def _ser_dob(self, d: date) -> str:
        return v.format_dob(d)

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _ser_ts(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=__import__("datetime").timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")


class CallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vapi_call_id: str
    patient_id: uuid.UUID | None
    caller_number: str | None
    started_at: datetime | None
    ended_at: datetime | None
    ended_reason: str | None
    transcript: str | None
    summary: str | None
    collected_payload: dict[str, Any] | None
    appointment: dict[str, Any] | None
    created_at: datetime


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


def envelope(data: Any = None, error: ErrorBody | dict | None = None) -> dict:
    """Consistent JSON envelope: { "data": ..., "error": null }"""
    if isinstance(error, ErrorBody):
        error = error.model_dump()
    return {"data": data, "error": error}
