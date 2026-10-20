"""Enums and message schemas shared by the harness (SPEC §4, §15)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Phase(str, Enum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    COMPLETE = "COMPLETE"    # terminal
    HANDOFF = "HANDOFF"      # terminal


TERMINAL = {Phase.COMPLETE, Phase.HANDOFF}


class EmailStatus(str, Enum):
    NOT_OFFERED = "not_offered"
    OFFERED = "offered"
    DECLINED = "declined"    # may change to yes before COMPLETE (P-1)
    SENT = "sent"            # terminal: never resent or recalled


class Awaiting(str, Enum):
    """What the agent's last message asked for; decides how yes/no is read."""
    NOTHING = "nothing"
    CASE_CONFIRM = "case_confirm"
    CASE_CHOICE = "case_choice"
    ANYTHING_ELSE = "anything_else"
    EMAIL = "email"
    HANDOFF_OFFER = "handoff_offer"


class Intent(str, Enum):
    DENIAL_QUESTION = "denial_question"
    STATUS_INQUIRY = "status_inquiry"
    DOCUMENT_SUBMISSION = "document_submission"
    NEXT_STEPS = "next_steps"
    GENERAL_CLAIM_QUESTION = "general_claim_question"


# ---------------------------------------------------------------- extraction

class IdentityExtract(BaseModel):
    """Raw values exactly as the user typed them; Python normalizes (E-1)."""
    full_name: str | None = None
    dob: str | None = None
    phone: str | None = None
    email: str | None = None
    id_last4: str | None = None
    id_type_stated: str | None = None


class CaseHint(BaseModel):
    case_id: str | None = None
    case_type: Literal["healthcare", "dental", "auto"] | None = None
    status: Literal["open", "closed", "denied"] | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = None
    amount: str | None = None


class EmotionSignal(BaseModel):
    type: Literal["neutral", "frustration", "anger", "anxiety", "confusion"] = "neutral"
    intensity: int = Field(default=0, ge=0, le=3)
    abusive: bool = False
    distress: bool = False   # severe distress (can't afford care, hopeless): prioritise a human (M-5)


class RefusalSignal(BaseModel):
    target: Literal["none", "field", "verification", "consent", "email"] = "none"
    field: str | None = None


class ExtractionResult(BaseModel):
    identity: IdentityExtract = IdentityExtract()
    policy_number: str | None = None
    caller_role: Literal["unknown", "policyholder", "representative"] = "unknown"
    actor_name: str | None = None
    intent: Intent | None = None
    case_hint: CaseHint = CaseHint()
    followup_topic: Literal[
        "submission_timing", "processing_time", "submission_method", "file_format",
        "receipt_confirmation", "doc_alternatives", "none"] = "none"
    emotion: EmotionSignal = EmotionSignal()
    refusal: RefusalSignal = RefusalSignal()
    off_topic: Literal["none", "out_of_role", "unrelated", "smalltalk", "non_english"] = "none"
    wants_human: bool = False
    is_done: bool = False
    switch_case: bool = False
    about_other_person: bool = False     # asks about someone else's claim (spouse, son, ...)
    asks_to_skip: bool = False
    asks_question: bool = False          # the message contains a claim-related question
    answer: Literal["yes", "no", "none"] = "none"   # reply to the agent's last yes/no question
    email_decision: Literal["none", "yes", "no", "unclear"] = "none"
    corrections: list[str] = []          # field names the user explicitly corrected


# ---------------------------------------------------------------- directive

class Action(str, Enum):
    # VERIFY_ID
    ASK_ID = "ASK_ID"
    ID_MISMATCH = "ID_MISMATCH"
    EXPLAIN_GATE = "EXPLAIN_GATE"
    OFFER_ALT_FIELDS = "OFFER_ALT_FIELDS"
    VERIFIED = "VERIFIED"
    ASK_ACTOR_NAME = "ASK_ACTOR_NAME"
    REQUEST_CONSENT = "REQUEST_CONSENT"
    CONSENT_PENDING = "CONSENT_PENDING"
    # RESOLVE_INTENT
    ASK_INTENT = "ASK_INTENT"
    CONFIRM_CASE = "CONFIRM_CASE"
    DISAMBIGUATE_CASE = "DISAMBIGUATE_CASE"
    NO_MATCHING_CASE = "NO_MATCHING_CASE"
    NO_CASES_ON_FILE = "NO_CASES_ON_FILE"
    CASE_RESOLVED = "CASE_RESOLVED"
    # PROCESS_CASE
    PRESENT_CASE = "PRESENT_CASE"
    ANSWER_FOLLOWUP = "ANSWER_FOLLOWUP"
    ANSWER_UNKNOWN = "ANSWER_UNKNOWN"
    OFFER_DOC_ALTERNATIVES = "OFFER_DOC_ALTERNATIVES"
    ASK_ANYTHING_ELSE = "ASK_ANYTHING_ELSE"
    # POST_PROCESS
    OFFER_EMAIL = "OFFER_EMAIL"
    RECONFIRM_EMAIL = "RECONFIRM_EMAIL"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_SKIPPED = "EMAIL_SKIPPED"
    CLOSE = "CLOSE"
    # global
    DEFLECT_OFF_TOPIC = "DEFLECT_OFF_TOPIC"
    OFFER_HANDOFF = "OFFER_HANDOFF"
    HANDOFF = "HANDOFF"
    CLARIFY = "CLARIFY"
    OTHER_PERSON_LOCKED = "OTHER_PERSON_LOCKED"   # A-5: identity is locked to the verified subject
    TRANSITION = "TRANSITION"     # internal: phase change with nothing to say


class Preface(str, Enum):
    ACK_EMOTION = "ACK_EMOTION"
    ACK_HINT = "ACK_HINT"
    DEFLECT = "DEFLECT"
    SMALLTALK = "SMALLTALK"
    THANKS = "THANKS"
    ENGLISH_ONLY = "ENGLISH_ONLY"


class Fact(BaseModel):
    """One grounded statement the agent may make. `value` is what may be said."""
    fact_id: str
    case_id: str
    kind: Literal["case", "status", "denial_reason", "documents_needed", "deadline",
                  "amount", "guidance", "next_step", "handoff"]
    value: str
    source: str
    keywords: tuple[str, ...] = ()       # T-3: text tokens that must appear
    turn: int = 0


class Step(BaseModel):
    action: Action
    params: dict[str, Any] = {}
    must_state: list[Fact] = []
    may_state: list[Fact] = []
    guidance: list[str] = []
    transition: Phase | None = None
    updates: dict[str, Any] = {}         # applied to the state copy by the orchestrator


class Directive(BaseModel):
    steps: list[Step] = []
    prefaces: list[Preface] = []
    preface_params: dict[str, Any] = {}
    must_state: list[Fact] = []
    may_state: list[Fact] = []
    guidance: list[str] = []

    def add(self, step: Step) -> None:
        self.steps.append(step)
        seen = {f.fact_id for f in self.allowed_facts}
        for f in step.must_state:
            if f.fact_id not in seen:
                self.must_state.append(f)
                seen.add(f.fact_id)
        for f in step.may_state:
            if f.fact_id not in seen:
                self.may_state.append(f)
                seen.add(f.fact_id)
        self.guidance.extend(g for g in step.guidance if g not in self.guidance)

    @property
    def allowed_facts(self) -> list[Fact]:
        return self.must_state + self.may_state


class AgentReply(BaseModel):
    text: str
    used_fact_ids: list[str] = []
