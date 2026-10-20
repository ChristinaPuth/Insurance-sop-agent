"""Representative authorization (SPEC §6). A mock: statuses come from consent_scenarios.json (A-3)."""
from __future__ import annotations

from typing import Literal

from . import normalize
from .data import InsuranceData, Representative

CONSENT_REASON = ("Health information belongs to the policyholder, so even family members need the "
                  "policyholder's OK before I can share it. I've sent an authorization request to the "
                  "policyholder's phone on file — it usually takes just a moment.")


def find_representative(data: InsuranceData, party_id: str, actor_name: str | None) -> Representative | None:
    """The caller must be listed for this policyholder (A-2). Names compare as token sets."""
    if not actor_name:
        return None
    want = normalize.name_tokens(actor_name)
    return next((r for r in data.representatives
                 if r.buyer_party_id == party_id and normalize.name_tokens(r.rep_name) == want), None)


def check(data: InsuranceData, scenario: str, checks_done: int) -> Literal["approved", "pending", "timeout"]:
    """One status check advances the scenario's sequence by one step; running out while pending is a timeout."""
    seq = data.consent_scenarios.get(scenario, data.consent_scenarios["default"])["status_sequence"]
    if checks_done >= len(seq):
        return "timeout"
    status = seq[checks_done]
    if status == "approved":
        return "approved"
    return "timeout" if checks_done + 1 >= len(seq) else "pending"
