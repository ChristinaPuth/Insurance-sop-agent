"""Per-turn orchestration (SPEC §3). Copies the state, never mutates the caller's object (G-4)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import fallbacks, normalize, policy
from .config import Thresholds
from .data import InsuranceData
from .facts import facts_said, missing_must_state, numbers_ok
from .llm_service import LLM, LLMError
from .prompts import STEP_HINTS
from .safety import guard, mask_message
from .schemas import Action, AgentReply, Directive, ExtractionResult, Phase, Preface, RefusalSignal, Step
from .state import PII_FIELDS, CaseQuery, Correction, SessionState, Turn, TurnTrace

MAX_TRANSITIONS = 3   # S-12

_RELATIVES = (r"son|daughter|wife|husband|spouse|partner|mother|father|mom|mum|dad|brother|sister|"
              r"child|kid|parent|friend|grandmother|grandfather|aunt|uncle|cousin|boyfriend|girlfriend")
_OTHER_PERSON = re.compile(
    rf"\b(my|our)\s+(?:{_RELATIVES})(?:'s)?\b.*\b(claim|policy|case|account)|"
    rf"\b(claim|policy|case|account)\b.*\b(?:for|of)\s+(?:my|our)\s+(?:{_RELATIVES})\b|"
    r"\bsomeone else'?s\b", re.IGNORECASE)


def mentions_other_person(text: str) -> bool:
    return bool(_OTHER_PERSON.search(text))


_REFUSE = re.compile(r"\b(don'?t|do not|won'?t|will not|rather not|not comfortable|refuse to|can'?t)\b"
                     r"[^.?!]{0,30}\b(give|share|provide|tell|say|disclose)\b[^.?!]{0,20}"
                     r"\b(ssn|social security|national id|id number|phone|email|date of birth|dob|birthday)\b",
                     re.IGNORECASE)
_REFUSED_FIELD = {"ssn": "id_last4", "social security": "id_last4", "national id": "id_last4",
                  "id number": "id_last4", "phone": "phone", "email": "email", "date of birth": "dob",
                  "dob": "dob", "birthday": "dob"}


_FIELD_NAMES = {"full_name": "full_name", "name": "full_name", "dob": "dob", "date_of_birth": "dob",
                "birthday": "dob", "birth_date": "dob", "phone": "phone", "phone_number": "phone", "email": "email",
                "email_address": "email", "id_last4": "id_last4", "ssn": "id_last4", "ssn_last4": "id_last4",
                "social": "id_last4", "national_id": "id_last4", "national_id_last4": "id_last4", "id": "id_last4"}


def fix_refusal(ext: ExtractionResult, text: str) -> tuple[ExtractionResult, str | None]:
    """Make a field refusal usable: map the model's field name to ours, or fill it from the keyword rule."""
    r = ext.refusal
    keyword = refused_field(text)
    if r.target == "field":
        field = _FIELD_NAMES.get((r.field or "").strip().lower().replace(" ", "_")) or keyword
        if field and field != r.field:
            return (ext.model_copy(update={"refusal": RefusalSignal(target="field", field=field)}),
                    f"refused field {r.field!r} read as {field}")
        return ext, None
    if r.target in ("none", "verification") and keyword:   # "won't give my SSN" names one field, not all of them
        return (ext.model_copy(update={"refusal": RefusalSignal(target="field", field=keyword),
                                       "asks_to_skip": False}),
                f"refused field {keyword} set by keyword rule (model said {r.target!r})")
    return ext, None


def refused_field(text: str) -> str | None:
    """'I don't want to give my SSN' -> 'id_last4'. Deterministic backup for the extractor."""
    m = _REFUSE.search(text)
    return _REFUSED_FIELD[m.group(3).lower()] if m else None

_NORMALIZERS = {
    "full_name": lambda v: " ".join(v.split()) if v.strip() else None,
    "dob": normalize.dob,
    "phone": normalize.phone,
    "email": normalize.email,
    "id_last4": normalize.id_last4,
}


def start_session(session_id: str) -> SessionState:
    s = SessionState(session_id=session_id)
    s.history.append(Turn(role="agent", text=fallbacks.GREETING))
    return s


# ---------------------------------------------------------------- memory

def merge_memory(state: SessionState, ext: ExtractionResult, masked_msg: str) -> SessionState:
    """E-2/E-3/E-4: store everything useful now, whatever the phase; never change the phase here."""
    s = state.model_copy(deep=True)
    if s.pending_party_id and not s.verified and ext.actor_name and s.actor_type == "representative":
        s.actor_name = " ".join(ext.actor_name.split())         # caller's own name may come after the match
    if not s.identity_locked:                                   # A-5: identity is frozen after verification
        if ext.caller_role == "representative":                 # A-4: before verification the role may change
            s.actor_type = "representative"
        if ext.actor_name and s.actor_type == "representative":
            s.actor_name = " ".join(ext.actor_name.split())
        for field in PII_FIELDS:
            raw = getattr(ext.identity, field)
            value = _NORMALIZERS[field](raw) if raw else None
            if value is None:
                continue
            if field in s.identity_claims and s.identity_claims[field] != value:
                s.corrections.append(Correction(field=field, turn=s.turn))
            s.identity_claims[field] = value
        stated = normalize.id_type(ext.identity.id_type_stated)
        if stated:
            s.id_type_stated = stated
        if ext.policy_number:
            s.policy_number = normalize.policy_number(ext.policy_number) or s.policy_number
    if ext.intent:
        s.intent = ext.intent
    if ext.switch_case:
        s.case_query = CaseQuery()
    hint = ext.case_hint.model_dump(exclude_none=True)
    if hint:
        if "case_id" in hint:
            hint["case_id"] = hint["case_id"].strip().upper()
        s.case_query = s.case_query.model_copy(update=hint)
    if not s.verified and ext.asks_question:                     # E-4
        s.pending_questions.append(masked_msg)
    return s


# ---------------------------------------------------------------- contexts

def _recent_history(state: SessionState, window: int) -> list[dict[str, str]]:
    return [{"role": t.role, "text": t.text} for t in state.history[-window:]]


def extraction_context(state: SessionState, data: InsuranceData, window: int) -> dict[str, Any]:
    """The extractor sees masked history and phase info; claim candidates only once verified."""
    ctx: dict[str, Any] = {
        "phase": state.phase.value,
        "awaiting_answer_to": state.awaiting.value,
        "caller_role_so_far": state.actor_type,
        "identity_fields_already_provided": state.provided_pii(),
        "recent_history_masked": _recent_history(state, window),
    }
    if state.verified and state.candidate_case_ids:
        claims = {c.case_id: c for c in data.claims if c.party_id == state.subject_party_id}
        ctx["candidate_claims"] = [f"{i}: {claims[i].case_type}, opened {claims[i].created_at}"
                                   for i in state.candidate_case_ids if i in claims]
    if state.resolved_case_id:
        ctx["claim_being_discussed"] = state.resolved_case_id
    return ctx


def response_context(state: SessionState, directive: Directive, data: InsuranceData,
                     window: int, latest_masked: str = "") -> dict[str, Any]:
    """G-2/X-2: only this turn's allowed facts; no PII; a first name only after verification."""
    display_name = None
    if state.verified and state.actor_type == "representative":
        display_name = (state.actor_name or "").split()[0] if state.actor_name else None
    elif state.verified:
        rec = next(p for p in data.policyholders if p.party_id == state.subject_party_id)
        display_name = rec.name.split()[0]
    return {
        "verified": state.verified,
        "display_name": display_name,
        "phase": state.phase.value,
        "prefaces": [p.value for p in directive.prefaces],
        "preface_params": directive.preface_params,
        "steps": [{"action": s.action.value, "instruction": STEP_HINTS[s.action.value],
                   "params": s.params} for s in directive.steps if s.action != Action.TRANSITION],
        "gate_reason": fallbacks.GATE_REASON,
        "field_labels": fallbacks.FIELD_LABELS,
        "MUST_STATE": [{"fact_id": f.fact_id, "text": f.value} for f in directive.must_state],
        "ALLOWED_FACTS": [{"fact_id": f.fact_id, "text": f.value} for f in directive.allowed_facts],
        "guidance": directive.guidance,
        "recent_history_masked": _recent_history(state, window),
        "CALLER_LATEST_MESSAGE": latest_masked,
    }


# ---------------------------------------------------------------- the turn

def _apply(state: SessionState, step: Step) -> SessionState:
    update = dict(step.updates)
    if step.transition is not None:
        update["phase"] = step.transition
    return state.model_copy(update=update, deep=True) if update else state


def handle_turn(state: SessionState, user_msg: str, llm: LLM | None, data: InsuranceData, today: date,
                thresholds: Thresholds = Thresholds()) -> tuple[SessionState, str]:
    s = state.model_copy(deep=True)
    s.turn += 1
    phase_before = s.phase
    notes: list[str] = []

    if s.phase in (Phase.COMPLETE, Phase.HANDOFF):
        text = ("This conversation has ended. Please start a new chat if you need more help."
                if s.phase == Phase.COMPLETE else "You're being transferred to a representative.")
        return s, text

    # ① extract (T-1)
    try:
        if llm is None:
            raise LLMError("no LLM configured")
        ext = llm.extract(user_msg, extraction_context(s, data, thresholds.history_window))
    except LLMError as exc:
        notes.append(f"extraction failed: {exc}")
        directive = Directive()
        directive.add(Step(action=Action.CLARIFY))
        text = (fallbacks.CONFIG_ERROR if exc.config_problem
                else fallbacks.BUSY if exc.rate_limited else fallbacks.render(directive))
        s.history += [Turn(role="user", text=mask_message(user_msg, ExtractionResult().identity)),
                      Turn(role="agent", text=text)]
        s.trace.append(TurnTrace(turn=s.turn, phase_before=phase_before, phase_after=s.phase,
                                 steps=["CLARIFY"], notes=notes))
        return s, text

    if not ext.about_other_person and mentions_other_person(user_msg):   # deterministic safety net (A-5)
        ext = ext.model_copy(update={"about_other_person": True, "switch_case": False})
        notes.append("about_other_person set by keyword rule")
    if s.phase == Phase.VERIFY_ID:                                       # safety net (M-6)
        ext, note = fix_refusal(ext, user_msg)
        if note:
            notes.append(note)
    masked = mask_message(user_msg, ext.identity)
    before = s
    s = merge_memory(s, ext, masked)
    pref, pref_params = policy.prefaces(before, s, ext)
    s.last_emotion = ext.emotion
    s.abuse_count += int(ext.emotion.abusive)
    s.anger_streak = s.anger_streak + 1 if (ext.emotion.type == "anger" and ext.emotion.intensity >= 3) else 0
    if any(getattr(ext.identity, f) for f in PII_FIELDS) and s.provided_pii() != before.provided_pii():
        s.no_progress_turns = 0
    elif s.phase == Phase.VERIFY_ID:
        s.no_progress_turns += 1
    if ext.off_topic not in policy.OFF_TOPIC and policy.is_relevant(ext):
        s.off_topic_streak = 0                                    # O-3: back on topic

    # ② decide, possibly chaining phases (S-12)
    directive = Directive(prefaces=pref, preface_params=pref_params)
    entered = False
    for _ in range(MAX_TRANSITIONS + 1):
        steps = policy.decide(s, ext, data, today, entered=entered, thresholds=thresholds)
        moved = False
        for step in steps:
            directive.add(step)
            s = _apply(s, step)
            moved = moved or step.transition is not None
        if not moved or s.phase in (Phase.COMPLETE, Phase.HANDOFF):
            break
        entered = True

    if s.verified and Preface.ACK_HINT in directive.prefaces:   # verified this turn: the case speaks for itself
        directive.prefaces.remove(Preface.ACK_HINT)

    # ③ respond, ④ check facts (T-3/T-6), ⑤ guard (X-4)
    reply: AgentReply | None = None
    strict = any(st.action == Action.HANDOFF for st in directive.steps)    # fixed wording: reference + notes
    if llm is not None and not strict:
        try:
            reply = llm.respond(response_context(s, directive, data, thresholds.history_window, masked))
        except LLMError as exc:
            notes.append(f"response fell back: {exc}")
    if reply is not None:
        problems = numbers_ok(reply.text, directive) + guard(reply.text, s, data)
        if problems:
            notes.append("reply rejected: " + "; ".join(problems))
            reply = None
    if reply is not None:
        said = facts_said(reply, directive)
        missing = missing_must_state(said, directive)
        text = reply.text
        if missing:                                               # T-4 / T-7
            notes.append("appended missing facts: " + ", ".join(f.fact_id for f in missing))
            text = text.rstrip() + " " + " ".join(f.value for f in missing)
            said += missing
    else:
        text = fallbacks.render(directive)
        said = list(directive.must_state)
        hits = guard(text, s, data)
        if hits:
            notes.append("guard hit on fallback: " + "; ".join(hits))

    recorded = {f.fact_id for f in s.discussed_facts}
    for f in said:
        if f.fact_id not in recorded:
            s.discussed_facts.append(f.model_copy(update={"turn": s.turn}))
            recorded.add(f.fact_id)

    s.history += [Turn(role="user", text=masked), Turn(role="agent", text=text)]
    s.trace.append(TurnTrace(
        turn=s.turn, phase_before=phase_before, phase_after=s.phase,
        extraction=_masked_extraction(ext), steps=[st.action.value for st in directive.steps],
        prefaces=[p.value for p in directive.prefaces], facts_recorded=[f.fact_id for f in said], notes=notes))
    return s, text


def _masked_extraction(ext: ExtractionResult) -> dict[str, Any]:
    d = ext.model_dump(exclude_defaults=True)
    if "identity" in d:
        d["identity"] = {k: ("<provided>" if k != "id_type_stated" else v) for k, v in d["identity"].items()}
    return d
