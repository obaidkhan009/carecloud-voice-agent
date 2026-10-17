import pytest

from app import validation as v


def test_phone_normalization():
    assert v.normalize_phone("(201) 555-0123") == "2015550123"
    assert v.normalize_phone("+1 201 555 0123") == "2015550123"
    assert v.normalize_phone("two zero one five five five zero one two three") == "2015550123"
    with pytest.raises(v.FieldError, match="10 digits"):
        v.normalize_phone("555")
    with pytest.raises(v.FieldError):
        v.normalize_phone("1115550123")


def test_dob():
    assert v.parse_dob("03/14/1985").isoformat() == "1985-03-14"
    assert v.parse_dob("1985-03-14").isoformat() == "1985-03-14"
    assert v.parse_dob("March 14, 1985").isoformat() == "1985-03-14"
    with pytest.raises(v.FieldError, match="future"):
        v.parse_dob("01/01/2099")
    with pytest.raises(v.FieldError):
        v.parse_dob("02/30/1990")


def test_state_zip_sex():
    assert v.normalize_state("nj") == "NJ"
    assert v.normalize_state("New Jersey") == "NJ"
    with pytest.raises(v.FieldError):
        v.normalize_state("ZZ")
    assert v.normalize_zip("08873") == "08873"
    assert v.normalize_zip("088731234") == "08873-1234"
    with pytest.raises(v.FieldError):
        v.normalize_zip("1234")
    assert v.normalize_sex("prefer not to say") == "Decline to Answer"
    assert v.normalize_sex("M") == "Male"
    with pytest.raises(v.FieldError):
        v.normalize_sex("blue")


def test_names_and_spelling():
    assert v.normalize_name("D-A-V-I-S", "last_name") == "Davis"
    assert v.normalize_name("o'brien", "last_name") == "O'brien"
    with pytest.raises(v.FieldError):
        v.normalize_name("", "first_name")
    with pytest.raises(v.FieldError):
        v.normalize_name("x" * 51, "first_name")


def test_sanitize_strips_control_chars():
    assert v.sanitize_text("Main\x00 St\n  Apt") == "Main St Apt"
