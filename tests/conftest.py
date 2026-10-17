import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["VAPI_SECRET"] = "test-secret"
os.environ["SEED_DATA"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


VALID = {
    "first_name": "Jane", "last_name": "Davis", "date_of_birth": "03/14/1985", "sex": "female",
    "phone_number": "(201) 555-0188", "address_line_1": "12 Main St", "city": "Somerset",
    "state": "New Jersey", "zip_code": "08873",
}
