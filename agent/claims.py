"""Subject-bound claims access (SPEC D-2). No method accepts a party_id."""
from __future__ import annotations

from .data import Claim, InsuranceData


class ClaimsRepo:
    def __init__(self, data: InsuranceData, authorized_party_id: str):
        self._party_id = authorized_party_id
        self._claims = tuple(c for c in data.claims if c.party_id == authorized_party_id)

    def list_claims(self) -> tuple[Claim, ...]:
        return self._claims

    def get_claim(self, case_id: str) -> Claim | None:
        """Returns None for unknown ids AND for other people's claims (C-1)."""
        wanted = case_id.strip().upper()
        return next((c for c in self._claims if c.case_id == wanted), None)


def repo_for(state, data: InsuranceData) -> ClaimsRepo | None:
    """The only way to obtain claim data: requires a verified subject."""
    if state.subject_party_id is None:
        return None
    return ClaimsRepo(data, state.subject_party_id)
