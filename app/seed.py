"""Two demo patients so reviewers can hit GET /patients and the duplicate-detection flow immediately."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Patient

SEED_PATIENTS = [
    dict(first_name="Jane", last_name="Doe", date_of_birth=date(1985, 3, 14), sex="Female",
         phone_number="2015550123", email="jane.doe@example.com", address_line_1="12 Main Street",
         address_line_2="Apt 4B", city="Somerset", state="NJ", zip_code="08873",
         insurance_provider="Aetna", insurance_member_id="W123456789", preferred_language="English",
         emergency_contact_name="John Doe", emergency_contact_phone="2015550199"),
    dict(first_name="Carlos", last_name="Rivera", date_of_birth=date(1972, 11, 2), sex="Male",
         phone_number="7325550147", address_line_1="880 Hamilton Street", city="New Brunswick",
         state="NJ", zip_code="08901", preferred_language="Spanish"),
]


def seed(db: Session) -> int:
    if db.scalar(select(Patient).limit(1)) is not None:
        return 0
    for row in SEED_PATIENTS:
        db.add(Patient(**row))
    db.commit()
    return len(SEED_PATIENTS)
