"""Per-conversation session state (SPEC §14). Never holds raw PII in history."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from .schemas import Awaiting, EmailStatus, EmotionSignal, Fact, Intent, Phase

PII_FIELDS = ("full_name", "dob", "phone", "email", "id_last4")


class CaseQuery(BaseModel):
    case_id: str | None = None
    case_type: str | None = None
    status: str | None = None
    month: int | None = None
    year: int | None = None
    amount: str | None = None

    def dimensions(self) -> int:
        """C-2: how many distinguishing clues the caller gave (case_id counts as decisive)."""
        time = self.month is not None or self.year is not None
        return sum([self.case_type is not None, self.status is not None, time, self.amount is not None])

    def is_empty(self) -> bool:
        return self.case_id is None and self.dimensions() == 0


class Correction(BaseModel):
    field: str
    turn: int


class Turn(BaseModel):
    role: Literal["user", "agent"]
    text: str                       # masked (X-1)


class TurnTrace(BaseModel):
    turn: int
    phase_before: Phase
    phase_after: Phase
    extraction: dict[str, Any] = {}  # masked
    steps: list[str] = []
    prefaces: list[str] = []
    facts_recorded: list[str] = []
    notes: list[str] = []            # fallbacks, guard hits, fact-check rejections


class HandoffRecord(BaseModel):
    reference: str
    reason: str
    user_message: str
    internal_summary: dict[str, Any]


class OutboxEmail(BaseModel):
    to_masked: str
    subject: str
    body: str


class SessionState(BaseModel):
    session_id: str = "SES-0000"
    phase: Phase = Phase.VERIFY_ID
    turn: int = 0
    awaiting: Awaiting = Awaiting.NOTHING

    # identity: actor / subject / authorization (A-1)
    actor_type: Literal["policyholder", "representative"] = "policyholder"
    actor_name: str | None = None
    identity_claims: dict[str, str] = {}          # normalized values, never shown unmasked
    id_type_stated: str | None = None             # "ssn" | "national_id"
    policy_number: str | None = None
    corrections: list[Correction] = []
    last_verify_fingerprint: str | None = None    # V-9
    subject_party_id: str | None = None
    identity_locked: bool = False
    consent_status: Literal["not_required", "pending", "approved", "timeout"] = "not_required"
    consent_checks: int = 0
    consent_scenario: str = "default"             # which consent_scenarios.json sequence the mock uses (A-3)
    pending_party_id: str | None = None           # subject matched, authorization not yet granted

    # counters
    verify_failures: int = 0
    gate_refusals: dict[str, int] = {}
    no_progress_turns: int = 0
    off_topic_streak: int = 0
    handoff_offered: bool = False
    escalation_level: int = 0                     # persuasion ladder L0-L4 (M-2)
    anger_streak: int = 0                         # consecutive turns at anger intensity 3
    abuse_count: int = 0
    last_emotion: EmotionSignal | None = None

    # cross-phase memory
    intent: Intent | None = None
    case_query: CaseQuery = CaseQuery()
    pending_questions: list[str] = []
    candidate_case_ids: list[str] = []
    resolved_case_id: str | None = None
    case_presented: bool = False

    # wrap-up
    discussed_facts: list[Fact] = []
    pending_followup: bool = False
    email_status: EmailStatus = EmailStatus.NOT_OFFERED
    email_reconfirmed: bool = False
    outbox: list[OutboxEmail] = []
    handoff: HandoffRecord | None = None

    # conversation
    history: list[Turn] = []
    trace: list[TurnTrace] = []

    @property
    def verified(self) -> bool:
        return self.subject_party_id is not None

    def provided_pii(self) -> list[str]:
        return [f for f in PII_FIELDS if f in self.identity_claims]
