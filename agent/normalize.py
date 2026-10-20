"""Normalization of user-supplied identity values (SPEC E-1)."""
from __future__ import annotations

import re
from datetime import date

from dateutil import parser as date_parser

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def name_tokens(value: str) -> frozenset[str]:
    """Lowercased name tokens; a set so 'Ma Tian' == 'Tian Ma' (V-3)."""
    cleaned = _NON_ALNUM.sub(" ", value.lower())
    return frozenset(cleaned.split())


def dob(value: str) -> str | None:
    """Any common date spelling -> ISO 'YYYY-MM-DD'. US month-first for ambiguous input."""
    try:
        parsed = date_parser.parse(value, dayfirst=False, fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if not isinstance(parsed, date) or parsed.year < 1900:
        return None
    return parsed.date().isoformat()


def phone(value: str) -> str | None:
    """Digits -> E.164. Assumes US numbers when 10 digits are given."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if len(digits) >= 8:
        return "+" + digits
    return None


def email(value: str) -> str | None:
    value = value.strip().lower()
    return value if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else None


def id_last4(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    return digits[-4:] if len(digits) >= 4 else None


def id_type(value: str | None) -> str | None:
    """Stated ID type -> 'ssn' | 'national_id' | None."""
    if not value:
        return None
    v = value.lower()
    if "ssn" in v or "social" in v:
        return "ssn"
    if "national" in v or "id" in v:
        return "national_id"
    return None


def policy_number(value: str) -> str | None:
    m = re.search(r"pol[\s-]*(\d+)", value, re.IGNORECASE)
    return f"POL-{m.group(1)}" if m else None
