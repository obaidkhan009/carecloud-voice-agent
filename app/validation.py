"""Pure validation/normalization helpers shared by the REST API and the voice-agent tools.

Everything the caller says arrives as messy speech-to-text ("five five five, one two three..." or
"March fourth nineteen ninety"). The LLM is asked to convert to digits/MM/DD/YYYY before calling us,
but these functions are tolerant on purpose and always return a canonical form or a clear, field-level
error message that the agent can read back to the caller.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")
_SEX_SYNONYMS = {
    "m": "Male", "male": "Male", "man": "Male", "boy": "Male",
    "f": "Female", "female": "Female", "woman": "Female", "girl": "Female",
    "other": "Other", "non-binary": "Other", "nonbinary": "Other", "non binary": "Other",
    "intersex": "Other", "x": "Other",
    "decline": "Decline to Answer", "decline to answer": "Decline to Answer",
    "prefer not to say": "Decline to Answer", "prefer not to answer": "Decline to Answer",
    "skip": "Decline to Answer", "no answer": "Decline to Answer", "rather not say": "Decline to Answer",
}

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\- ]{0,49}$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9\-]{1,50}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_WORD_DIGITS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


class FieldError(ValueError):
    """Validation failure for one field, with a message safe to read aloud to a caller."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


def sanitize_text(value: str | None, max_len: int = 200) -> str | None:
    """Strip control characters, collapse whitespace, cap length. Basic input sanitization for every string."""
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", str(value))
    value = _CONTROL_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_len]


def normalize_name(value: str, field: str) -> str:
    value = sanitize_text(value, 60) or ""
    # Callers often spell names: "D-A-V-I-S" or "d a v i s" -> "Davis"
    if re.fullmatch(r"(?:[A-Za-z][\s\-]+){2,}[A-Za-z]", value):
        value = re.sub(r"[\s\-]+", "", value)
    value = re.sub(r"[^A-Za-z'\- ]", "", value)
    if not value or not _NAME_RE.fullmatch(value):
        raise FieldError(field, f"{field.replace('_', ' ')} must be 1 to 50 letters (hyphens and apostrophes allowed).")
    return " ".join(part[:1].upper() + part[1:].lower() for part in value.split(" ")) if value.islower() or value.isupper() else value


def normalize_phone(value: str, field: str = "phone_number") -> str:
    raw = sanitize_text(value, 80) or ""
    words = [_WORD_DIGITS.get(w.lower(), w) for w in re.split(r"[\s,\-\.()]+", raw) if w]
    digits = re.sub(r"\D", "", "".join(words))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise FieldError(field, f"A U.S. phone number needs exactly 10 digits, I heard {len(digits)}.")
    if digits[0] in "01" or digits[3] in "01":
        raise FieldError(field, "That doesn't look like a valid U.S. number; the area code and exchange can't start with 0 or 1.")
    return digits


def format_phone(digits: str | None) -> str | None:
    if not digits:
        return digits
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def parse_dob(value: str | date | datetime, field: str = "date_of_birth") -> date:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        parsed = value
    else:
        text = sanitize_text(value, 40) or ""
        parsed = None
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y", "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y"):
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise FieldError(field, "I couldn't read that date. Please give it as month, day, and four-digit year.")
    today = date.today()
    if parsed > today:
        raise FieldError(field, "That date of birth is in the future. Could you repeat the year?")
    if parsed.year < 1900:
        raise FieldError(field, "That year seems too early. Could you repeat the year?")
    return parsed


def format_dob(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def normalize_sex(value: str, field: str = "sex") -> str:
    text = (sanitize_text(value, 40) or "").lower().strip(". ")
    if text in {s.lower() for s in SEX_VALUES}:
        return next(s for s in SEX_VALUES if s.lower() == text)
    if text in _SEX_SYNONYMS:
        return _SEX_SYNONYMS[text]
    raise FieldError(field, "Please answer Male, Female, Other, or Decline to answer.")


def normalize_state(value: str, field: str = "state") -> str:
    text = (sanitize_text(value, 40) or "").strip(". ")
    code = text.upper().replace(".", "")
    if code in US_STATES:
        return code
    if text.lower() in _STATE_BY_NAME:
        return _STATE_BY_NAME[text.lower()]
    raise FieldError(field, "Please give a valid U.S. state, for example New Jersey or NJ.")


def normalize_zip(value: str, field: str = "zip_code") -> str:
    raw = sanitize_text(value, 40) or ""
    words = [_WORD_DIGITS.get(w.lower(), w) for w in re.split(r"[\s,\.]+", raw) if w]
    text = "".join(words)
    digits = re.sub(r"\D", "", text)
    if len(digits) == 9:
        text = f"{digits[:5]}-{digits[5:]}"
    elif len(digits) == 5:
        text = digits
    if not _ZIP_RE.fullmatch(text):
        raise FieldError(field, "A ZIP code is 5 digits, or 9 digits for ZIP plus four.")
    return text


def normalize_email(value: str | None, field: str = "email") -> str | None:
    text = sanitize_text(value, 254)
    if not text:
        return None
    text = text.lower().replace(" at ", "@").replace(" dot ", ".").replace(" ", "")
    if not _EMAIL_RE.fullmatch(text):
        raise FieldError(field, "That email address doesn't look valid. Could you spell it out?")
    return text


def normalize_member_id(value: str | None, field: str = "insurance_member_id") -> str | None:
    text = sanitize_text(value, 60)
    if not text:
        return None
    text = text.replace(" ", "").upper()
    if not _MEMBER_ID_RE.fullmatch(text):
        raise FieldError(field, "The member ID should be letters and numbers only.")
    return text


def normalize_language(value: str | None) -> str:
    text = sanitize_text(value, 50)
    if not text:
        return "English"
    return text[:1].upper() + text[1:]


def required_text(value: str | None, field: str, max_len: int) -> str:
    text = sanitize_text(value, max_len)
    if not text:
        raise FieldError(field, f"{field.replace('_', ' ')} is required.")
    return text


# Map used by the agent's `validate_field` tool and by Pydantic validators.
NORMALIZERS = {
    "first_name": lambda v: normalize_name(v, "first_name"),
    "last_name": lambda v: normalize_name(v, "last_name"),
    "date_of_birth": lambda v: format_dob(parse_dob(v)),
    "sex": normalize_sex,
    "phone_number": normalize_phone,
    "email": normalize_email,
    "address_line_1": lambda v: required_text(v, "address_line_1", 200),
    "address_line_2": lambda v: sanitize_text(v, 200),
    "city": lambda v: required_text(v, "city", 100),
    "state": normalize_state,
    "zip_code": normalize_zip,
    "insurance_provider": lambda v: sanitize_text(v, 100),
    "insurance_member_id": normalize_member_id,
    "preferred_language": normalize_language,
    "emergency_contact_name": lambda v: normalize_name(v, "emergency_contact_name") if v else None,
    "emergency_contact_phone": lambda v: normalize_phone(v, "emergency_contact_phone") if v else None,
}


def validate_one(field: str, value) -> str | None:
    if field not in NORMALIZERS:
        raise FieldError(field, f"Unknown field '{field}'.")
    return NORMALIZERS[field](value)
