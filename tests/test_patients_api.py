from tests.conftest import VALID


def test_seed_and_list(client):
    r = client.get("/patients")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert any(p["last_name"] == "Doe" for p in body["data"])


def test_create_normalizes_and_returns_201(client):
    r = client.post("/patients", json=VALID)
    assert r.status_code == 201, r.text
    p = r.json()["data"]
    assert p["phone_number"] == "2015550188"
    assert p["state"] == "NJ"
    assert p["sex"] == "Female"
    assert p["date_of_birth"] == "03/14/1985"
    assert p["preferred_language"] == "English"
    assert p["patient_id"] and p["created_at"].endswith("Z")


def test_create_validation_errors_are_field_level(client):
    bad = {**VALID, "date_of_birth": "01/01/2099", "phone_number": "555", "state": "ZZ"}
    r = client.post("/patients", json=bad)
    assert r.status_code == 422
    details = {d["field"]: d["message"] for d in r.json()["error"]["details"]}
    assert "date_of_birth" in details and "future" in details["date_of_birth"]
    assert "phone_number" in details
    assert "state" in details


def test_missing_required_field(client):
    body = {k: v for k, v in VALID.items() if k != "city"}
    r = client.post("/patients", json=body)
    assert r.status_code == 422
    assert any(d["field"] == "city" for d in r.json()["error"]["details"])


def test_unknown_field_rejected(client):
    r = client.post("/patients", json={**VALID, "ssn": "123"})
    assert r.status_code == 422


def test_get_filters_update_delete(client):
    pid = client.post("/patients", json=VALID).json()["data"]["patient_id"]

    assert client.get(f"/patients/{pid}").status_code == 200
    assert client.get("/patients/not-a-uuid").status_code == 400
    assert client.get("/patients/00000000-0000-0000-0000-000000000000").status_code == 404

    assert any(p["patient_id"] == pid for p in client.get("/patients?last_name=davis").json()["data"])
    assert any(p["patient_id"] == pid for p in client.get("/patients?phone_number=201-555-0188").json()["data"])
    assert any(p["patient_id"] == pid for p in client.get("/patients?date_of_birth=03/14/1985").json()["data"])
    assert client.get("/patients?date_of_birth=99/99/9999").status_code == 422

    r = client.put(f"/patients/{pid}", json={"city": "Edison", "email": "jane@example.com"})
    assert r.status_code == 200
    assert r.json()["data"]["city"] == "Edison"
    assert r.json()["data"]["email"] == "jane@example.com"
    assert r.json()["data"]["last_name"] == "Davis"
    assert client.put(f"/patients/{pid}", json={}).status_code == 400
    assert client.put(f"/patients/{pid}", json={"zip_code": "12"}).status_code == 422

    r = client.delete(f"/patients/{pid}")
    assert r.status_code == 200 and r.json()["data"]["deleted_at"]
    assert client.get(f"/patients/{pid}").status_code == 404
    assert client.delete(f"/patients/{pid}").status_code == 404
    assert not any(p["patient_id"] == pid for p in client.get("/patients").json()["data"])


def test_health(client):
    assert client.get("/health").json()["data"]["status"] == "ok"


def test_dashboard_served(client):
    r = client.get("/dashboard")
    assert r.status_code == 200 and "Patient Registrations" in r.text
