"""Read-only fixture data (SPEC D-1)."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Policyholder(_Frozen):
    party_id: str
    name: str
    policy_number: str
    dob: str
    id_type: str            # "ssn_last4" | "national_id_last4"
    id_last4: str
    phone: str
    email: str
    name_aliases: tuple[str, ...] = ()
    phone_aliases: tuple[str, ...] = ()
    email_aliases: tuple[str, ...] = ()


class Claim(_Frozen):
    case_id: str
    party_id: str
    case_type: str
    created_at: str
    status: str
    summary: str
    denial_reason: str | None = None
    documents_needed: tuple[str, ...] = ()
    appeal_deadline: str | None = None
    expected_reimbursement_amount: str
    allowed_max_amount: str
    net_pay: str
    net_fee: str

    def amount(self, field: str) -> Decimal:
        return Decimal(getattr(self, field))


class Representative(_Frozen):
    rep_name: str
    relationship: str
    buyer_name: str
    buyer_party_id: str


class InsuranceData(_Frozen):
    policyholders: tuple[Policyholder, ...]
    claims: tuple[Claim, ...]
    representatives: tuple[Representative, ...]
    claim_schema: Mapping[str, Any]
    guideline: Mapping[str, Any]
    consent_scenarios: Mapping[str, Any]

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


def _freeze(obj: Any) -> Any:
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


def load_data(data_dir: Path) -> InsuranceData:
    def read(name: str) -> Any:
        return json.loads((Path(data_dir) / name).read_text(encoding="utf-8"))

    return InsuranceData(
        policyholders=tuple(Policyholder(**p) for p in read("policyholders.json")),
        claims=tuple(Claim(**c) for c in read("claims.json")),
        representatives=tuple(Representative(**r) for r in read("representatives.json")),
        claim_schema=_freeze(read("claim_schema.json")),
        guideline=_freeze(read("required_document_guideline.json")),
        consent_scenarios=_freeze(read("consent_scenarios.json")),
    )
