"""Deterministic email summary (SPEC P-5, P-6) and handoff records (H-2, H-3)."""
from __future__ import annotations

from typing import Protocol

from .data import InsuranceData
from .safety import mask_email
from .state import HandoffRecord, OutboxEmail, SessionState

SECTION_KINDS = {
    "Claim status": ("case", "status", "denial_reason"),
    "Next steps": ("documents_needed", "deadline", "guidance", "next_step"),
    "Amounts discussed": ("amount",),
}


def on_file_email(state: SessionState, data: InsuranceData) -> str | None:
    """P-4 / A-6: always the subject's email on file, never an address typed in chat."""
    rec = next((p for p in data.policyholders if p.party_id == state.subject_party_id), None)
    return rec.email if rec else None


def render_email(state: SessionState, data: InsuranceData) -> OutboxEmail:
    """Sections render only when facts of that kind were actually said (P-5)."""
    facts = state.discussed_facts
    case_ids = list(dict.fromkeys(f.case_id for f in facts))
    subject = "Summary of your call" + (f" — Claim {', '.join(case_ids)}" if case_ids else "")
    lines = ["Hello,", "", "Here is a summary of your claims support conversation.", ""]
    for title, kinds in SECTION_KINDS.items():
        items = [f for f in facts if f.kind in kinds]
        if not items:
            continue
        lines.append(title)
        lines.extend(f"  • {f.value}" for f in dict((f.fact_id, f) for f in items).values())
        lines.append("")
    lines += [f"Reference: {state.session_id}", "", "Claims Support"]
    return OutboxEmail(to_masked=mask_email(on_file_email(state, data) or ""), subject=subject,
                       body="\n".join(lines))


class EmailSender(Protocol):
    def send(self, email: OutboxEmail) -> None: ...


class MockEmailSender:
    """P-6: nothing leaves the process; the UI shows the outbox as 'not actually sent'."""

    def __init__(self) -> None:
        self.sent: list[OutboxEmail] = []

    def send(self, email: OutboxEmail) -> None:
        self.sent.append(email)


def build_handoff(state: SessionState, reason: str) -> HandoffRecord:
    """H-3: internal summary never contains PII values; claim data only if verified."""
    ref = f"H-{state.session_id[-4:]}{state.turn:02d}"
    internal = {
        "reason": reason,
        "verified": state.verified,
        "caller_type": state.actor_type,
        "consent_status": state.consent_status,
        "identity_fields_provided": state.provided_pii(),
        "verification_failures": state.verify_failures,
        "caller_stated_intent": state.intent.value if state.intent else None,
        "caller_stated_case_hint": state.case_query.model_dump(exclude_none=True),
        "last_emotion": state.last_emotion.model_dump() if state.last_emotion else None,
    }
    if state.verified:
        internal["party_id"] = state.subject_party_id
        internal["resolved_case_id"] = state.resolved_case_id
        internal["facts_discussed"] = [f.value for f in state.discussed_facts]
    return HandoffRecord(reference=ref, reason=reason, internal_summary=internal,
                         user_message=f"Transferring you to a representative. Reference {ref}.")
