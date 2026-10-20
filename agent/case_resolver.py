"""Clues -> claim candidates (SPEC §7). Pure Python; the LLM only supplies the clues."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from .claims import ClaimsRepo
from .data import Claim
from .schemas import Intent
from .state import CaseQuery

AMOUNT_FIELDS = ("expected_reimbursement_amount", "allowed_max_amount", "net_pay", "net_fee")
SPECIFIC_ENOUGH = 2   # C-2


@dataclass(frozen=True)
class Resolution:
    kind: Literal["resolved", "confirm", "disambiguate", "no_match", "no_cases", "ask_intent"]
    case_ids: tuple[str, ...] = ()
    unknown_case_id: str | None = None


def _amount_matches(claim: Claim, amount: str) -> bool:
    try:
        wanted = Decimal(amount.replace("$", "").replace(",", ""))
    except InvalidOperation:
        return False
    return any(claim.amount(f) == wanted for f in AMOUNT_FIELDS)


def _matches(claim: Claim, q: CaseQuery) -> bool:
    year, month = int(claim.created_at[:4]), int(claim.created_at[5:7])
    return all([
        q.case_type is None or claim.case_type == q.case_type,
        q.status is None or claim.status == q.status,
        q.month is None or month == q.month,
        q.year is None or year == q.year,
        q.amount is None or _amount_matches(claim, q.amount),
    ])


def effective_query(q: CaseQuery, intent: Intent | None) -> CaseQuery:
    """A question about a denial is a clue in itself: the claim was denied."""
    if intent == Intent.DENIAL_QUESTION and q.status is None:
        return q.model_copy(update={"status": "denied"})
    return q


def resolve(repo: ClaimsRepo, q: CaseQuery, intent: Intent | None) -> Resolution:
    has_intent = intent is not None
    q = effective_query(q, intent)
    claims = repo.list_claims()
    if not claims:
        return Resolution("no_cases")

    if q.case_id:                                                   # C-1
        claim = repo.get_claim(q.case_id)
        if claim is None:
            return Resolution("no_match", unknown_case_id=q.case_id.upper())
        return Resolution("resolved", (claim.case_id,))

    if q.is_empty() and not has_intent:
        return Resolution("ask_intent")

    # most recent first: recency only orders the list, never picks for the caller (C-5)
    found = sorted((c for c in claims if _matches(c, q)), key=lambda c: c.created_at, reverse=True)
    ids = tuple(c.case_id for c in found)
    if not found:
        return Resolution("no_match")                               # C-6
    if len(found) > 1:
        return Resolution("disambiguate", ids)                      # C-5
    if q.dimensions() >= SPECIFIC_ENOUGH:
        return Resolution("resolved", ids)                          # C-3
    return Resolution("confirm", ids)                               # C-4
