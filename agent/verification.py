"""Deterministic identity verification (SPEC §5). The LLM never decides a match."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from . import normalize
from .data import Policyholder
from .state import PII_FIELDS

MIN_MATCHES = 3


@dataclass(frozen=True)
class RecordMatch:
    party_id: str
    matched: frozenset[str]
    conflicts: frozenset[str]
    neutral: frozenset[str] = field(default_factory=frozenset)   # V-7 type mismatch


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    party_id: str | None = None
    matched: frozenset[str] = frozenset()
    type_mismatch: bool = False


def _field_status(fname: str, value: str, rec: Policyholder, id_type_stated: str | None) -> str:
    """Return 'match' | 'conflict' | 'neutral' for one claimed field against one record."""
    if fname == "full_name":
        claimed = normalize.name_tokens(value)
        known = [normalize.name_tokens(n) for n in (rec.name, *rec.name_aliases)]
        return "match" if claimed in known else "conflict"
    if fname == "dob":
        return "match" if value == rec.dob else "conflict"
    if fname == "phone":
        return "match" if value in (rec.phone, *rec.phone_aliases) else "conflict"   # exact only (V-5)
    if fname == "email":
        known = {e.lower() for e in (rec.email, *rec.email_aliases)}
        return "match" if value in known else "conflict"
    if fname == "id_last4":
        record_type = "ssn" if rec.id_type.startswith("ssn") else "national_id"
        if id_type_stated and id_type_stated != record_type:
            return "neutral"
        return "match" if value == rec.id_last4 else "conflict"
    raise ValueError(fname)


def match_record(claims: dict[str, str], rec: Policyholder, id_type_stated: str | None) -> RecordMatch:
    status = {f: _field_status(f, v, rec, id_type_stated) for f, v in claims.items() if f in PII_FIELDS}
    return RecordMatch(
        party_id=rec.party_id,
        matched=frozenset(f for f, s in status.items() if s == "match"),
        conflicts=frozenset(f for f, s in status.items() if s == "conflict"),
        neutral=frozenset(f for f, s in status.items() if s == "neutral"),
    )


def verify(claims: dict[str, str], records: tuple[Policyholder, ...],
           id_type_stated: str | None = None, policy_number: str | None = None) -> VerifyResult:
    """V-1: >=3 PII on ONE record, no conflicts among provided fields, exactly one such record.
    V-2: a policy number only narrows the candidates when it matches one."""
    candidates = records
    if policy_number:
        narrowed = tuple(r for r in records if r.policy_number == policy_number)
        candidates = narrowed or records

    winners = []
    type_mismatch = False
    for rec in candidates:
        m = match_record(claims, rec, id_type_stated)
        type_mismatch = type_mismatch or bool(m.neutral)
        if not m.conflicts and len(m.matched) >= MIN_MATCHES:
            winners.append(m)
    if len(winners) == 1:
        w = winners[0]
        return VerifyResult(ok=True, party_id=w.party_id, matched=w.matched)
    return VerifyResult(ok=False, type_mismatch=type_mismatch)


def fingerprint(claims: dict[str, str], id_type_stated: str | None) -> str:
    """V-9: identical claimed values => identical fingerprint => not a new attempt."""
    payload = json.dumps({"c": claims, "t": id_type_stated}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
