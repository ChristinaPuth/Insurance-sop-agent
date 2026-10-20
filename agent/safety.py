"""PII masking (SPEC X-1, X-3) and the output guard tripwire (X-4)."""
from __future__ import annotations

import re

from .data import InsuranceData
from .schemas import IdentityExtract
from .state import SessionState

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_LAST4 = re.compile(r"\b\d{4}\b")

PLACEHOLDERS = {"full_name": "[NAME]", "dob": "[DOB]", "phone": "[PHONE]", "email": "[EMAIL]", "id_last4": "[ID_LAST4]"}


def mask_message(text: str, identity: IdentityExtract) -> str:
    """X-1: replace the raw spans the extractor found, then sweep generic PII patterns."""
    out = text
    for field, placeholder in PLACEHOLDERS.items():
        raw = getattr(identity, field)
        if raw and raw in out:
            out = out.replace(raw, placeholder)
    out = _EMAIL.sub("[EMAIL]", out)
    out = _PHONE.sub("[PHONE]", out)
    out = _ISO_DATE.sub("[DATE]", out)
    if identity.id_last4:
        out = _LAST4.sub("[NUM]", out)
    return out


def mask_value(field: str, value: str) -> str:
    """X-3: display form for debug panels and logs."""
    if field == "dob":
        return value[:4] + "-**-**"
    if field == "id_last4":
        return "***" + value[-1:]
    if field == "phone":
        return "***-" + value[-4:]
    if field == "email":
        return mask_email(value)
    if field == "full_name":
        return value.split()[0][:1].upper() + "***" if value.split() else "***"
    return "***"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}{'*' * max(len(local) - 1, 3)}@{domain}"


def _claim_blacklist(data: InsuranceData) -> set[str]:
    terms: set[str] = set()
    for c in data.claims:
        terms.add(c.case_id.lower())
        terms.update(d.lower() for d in c.documents_needed)
        for field in ("allowed_max_amount", "expected_reimbursement_amount", "net_pay", "net_fee"):
            amount = getattr(c, field)
            if amount not in ("0.00", "0"):
                terms.add(amount)
                terms.add(amount.removesuffix(".00"))
        for d in (c.created_at, c.appeal_deadline):
            if d:
                terms.add(d)
    return {t for t in terms if len(t) >= 4}


def guard(text: str, state: SessionState, data: InsuranceData) -> list[str]:
    """X-4: returns violations. Access control is the guarantee; this only raises an alarm."""
    hits = []
    low = text.lower()
    if not state.verified:
        hits += [f"pre-verification claim term '{t}'" for t in sorted(_claim_blacklist(data)) if t in low]
    dob = state.identity_claims.get("dob")
    if dob and dob in text:
        hits.append("full dob echoed")
    phone = state.identity_claims.get("phone")
    if phone and phone[-10:] in re.sub(r"\D", "", text):
        hits.append("full phone echoed")
    return hits
