"""The SOP state machine (SPEC §2, §5, §7, §11). Pure: no LLM, no I/O, no mutation of inputs (G-4).

`decide` returns the steps for the current phase. Signals that answer the agent's last question
(yes/no, done, email decision) are only read in the phase where the turn started (`entered=False`);
a phase entered during this turn acts on memory alone.
"""
from __future__ import annotations

from datetime import date

from . import case_resolver, consent, guidance
from .claims import repo_for
from .data import Claim, InsuranceData
from .facts import claim_facts, human_date
from .safety import mask_email
from .schemas import Action, Awaiting, EmailStatus, ExtractionResult, Phase, Preface, Step
from .state import PII_FIELDS, CaseQuery, SessionState
from .summary import build_handoff, on_file_email, render_email
from .verification import MIN_MATCHES, fingerprint, verify

OFF_TOPIC = ("unrelated", "out_of_role")


def _handoff(state: SessionState, reason: str) -> Step:
    record = build_handoff(state, reason)
    return Step(action=Action.HANDOFF, transition=Phase.HANDOFF,
                params={"reference": record.reference, "unverified": not state.verified},
                updates={"handoff": record, "awaiting": Awaiting.NOTHING})


def is_relevant(ext: ExtractionResult) -> bool:
    ident = ext.identity
    return bool(ext.asks_question or ext.intent or ext.is_done or ext.answer != "none"
                or ext.email_decision != "none" or ext.switch_case or ext.asks_to_skip
                or any(getattr(ident, f) for f in PII_FIELDS) or ext.policy_number
                or ext.case_hint.model_dump(exclude_none=True))


def decide(state: SessionState, ext: ExtractionResult, data: InsuranceData, today: date,
           entered: bool = False, thresholds=None) -> list[Step]:
    if state.phase in (Phase.COMPLETE, Phase.HANDOFF):
        return []
    if not entered:
        glob = _global(state, ext, thresholds)
        if glob is not None:
            return glob
    handler = {
        Phase.VERIFY_ID: _verify_id,
        Phase.RESOLVE_INTENT: _resolve_intent,
        Phase.PROCESS_CASE: _process_case,
        Phase.POST_PROCESS: _post_process,
    }[state.phase]
    return handler(state, ext, data, today, entered)


# ---------------------------------------------------------------- global rules

def _global(state: SessionState, ext: ExtractionResult, thresholds) -> list[Step] | None:
    offer_at = thresholds.off_topic_offer if thresholds else 3
    handoff_at = thresholds.off_topic_handoff if thresholds else 4

    if ext.wants_human or (state.awaiting == Awaiting.HANDOFF_OFFER and ext.answer == "yes"):
        return [_handoff(state, "caller requested a representative")]                  # H-1
    if state.abuse_count >= 2:
        return [_handoff(state, "abusive language after de-escalation")]               # M-5
    if state.verified and state.actor_type == "policyholder" and ext.caller_role == "representative":
        return [_handoff(state, "caller identity changed after verification")]            # A-4
    if state.verified and ext.about_other_person:                                       # A-5: identity locked
        return [Step(action=Action.OTHER_PERSON_LOCKED, updates={"awaiting": Awaiting.ANYTHING_ELSE})]

    if ext.off_topic in OFF_TOPIC and not is_relevant(ext):                            # O-1
        streak = state.off_topic_streak + 1
        if state.handoff_offered and streak >= handoff_at:
            return [_handoff(state, "repeated out-of-scope questions")]                # O-3
        if streak >= offer_at:
            return [Step(action=Action.OFFER_HANDOFF,
                         updates={"off_topic_streak": streak, "handoff_offered": True,
                                  "awaiting": Awaiting.HANDOFF_OFFER})]
        return [Step(action=Action.DEFLECT_OFF_TOPIC,
                     params={"nudge": "claim" if state.verified else "verify", "kind": ext.off_topic},
                     updates={"off_topic_streak": streak})]
    return None


def prefaces(before: SessionState, after: SessionState, ext: ExtractionResult) -> tuple[list[Preface], dict]:
    out: list[Preface] = []
    params: dict = {}
    emo = ext.emotion
    prev = before.last_emotion
    if emo.type != "neutral" and emo.intensity >= 2 and (
            prev is None or prev.type != emo.type or emo.intensity > prev.intensity):    # M-7
        out.append(Preface.ACK_EMOTION)
        params["emotion"] = emo.type
    if not after.verified and (after.intent != before.intent or after.case_query != before.case_query):
        hint = hint_text(after.case_query)
        if hint:                                                                         # C-8
            out.append(Preface.ACK_HINT)
            params["hint_text"] = hint
    if ext.off_topic in OFF_TOPIC and is_relevant(ext):                                 # O-2
        out.append(Preface.DEFLECT)
    if ext.off_topic == "non_english":                                                   # G-5, not counted
        out.append(Preface.ENGLISH_ONLY)
    return out, params


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]


def hint_text(q: CaseQuery) -> str | None:
    """Echo only the caller's own clues; never anything looked up (C-8)."""
    if q.is_empty():
        return None
    words = ["your"]
    if q.status:
        words.append(q.status)
    if q.case_type:
        words.append(q.case_type)
    words.append("claim")
    if q.case_id:
        words.append(q.case_id)
    if q.month:
        words.append("from " + MONTH_NAMES[q.month - 1] + (f" {q.year}" if q.year else ""))
    elif q.year:
        words.append(f"from {q.year}")
    return " ".join(words)


# ---------------------------------------------------------------- VERIFY_ID

def _verify_id(state: SessionState, ext: ExtractionResult, data: InsuranceData, today: date,
               entered: bool) -> list[Step]:
    provided = state.provided_pii()
    missing = [f for f in PII_FIELDS if f not in provided]
    refused = ext.refusal.field if ext.refusal.target == "field" else None
    options = [f for f in missing if f != refused] or missing
    needed = max(MIN_MATCHES - len(provided), 0)

    if state.consent_status == "pending":
        return _consent_check(state, data)
    if state.pending_party_id:                                                          # matched, need caller name
        return _start_consent(state, state.pending_party_id, data, state.last_verify_fingerprint)

    if len(provided) >= MIN_MATCHES:
        fp = fingerprint(state.identity_claims, state.id_type_stated)
        if fp == state.last_verify_fingerprint:                                         # V-9: not a new attempt
            return [Step(action=Action.ID_MISMATCH, params={"options": options})]
        result = verify(state.identity_claims, data.policyholders, state.id_type_stated, state.policy_number)
        if result.ok and state.actor_type == "representative":                          # A-2
            return _start_consent(state, result.party_id, data, fp)
        if result.ok:
            return [Step(action=Action.VERIFIED, transition=Phase.RESOLVE_INTENT,
                         updates={"subject_party_id": result.party_id, "identity_locked": True,
                                  "last_verify_fingerprint": fp, "no_progress_turns": 0})]
        failures = state.verify_failures + 1
        updated = state.model_copy(update={"verify_failures": failures})
        if failures >= 3:
            step = _handoff(updated, "identity verification failed 3 times")              # S-2
            step.updates.update({"verify_failures": failures, "last_verify_fingerprint": fp})
            return [step]
        return [Step(action=Action.ID_MISMATCH, params={"options": options},
                     updates={"verify_failures": failures, "last_verify_fingerprint": fp})]

    ask = {"missing": options, "needed": needed}
    ladder = _ladder(state, ext, gate="verification")
    if ladder is not None:
        level, updates = ladder
        if level >= 4:
            step = _handoff(state, "caller declined verification repeatedly")
            step.updates.update(updates)
            return [step]
        if level == 3:
            updates.update({"awaiting": Awaiting.HANDOFF_OFFER, "handoff_offered": True})
            return [Step(action=Action.OFFER_HANDOFF, params={**ask, "gate": "verification"}, updates=updates)]
        if level == 2:
            return [Step(action=Action.OFFER_ALT_FIELDS, params={"options": options, "needed": needed,
                                                                  "mention_handoff": True}, updates=updates)]
        if level == 1:
            return [Step(action=Action.EXPLAIN_GATE, params=ask, updates=updates)]
        if updates:
            return [Step(action=Action.ASK_ID, params=ask, updates=updates)]
    if refused:                                                                          # M-6
        return [Step(action=Action.OFFER_ALT_FIELDS, params={"options": options, "needed": needed})]
    if ext.asks_to_skip or ext.refusal.target == "verification" or ext.asks_question:
        return [Step(action=Action.EXPLAIN_GATE, params=ask)]
    return [Step(action=Action.ASK_ID, params=ask)]


def _start_consent(state: SessionState, party_id: str, data: InsuranceData, fp: str | None) -> list[Step]:
    """Subject's PII matched; the caller is a representative. Authorization comes before any claim data."""
    base = {"pending_party_id": party_id, "identity_locked": True, "last_verify_fingerprint": fp}
    if not state.actor_name:
        return [Step(action=Action.ASK_ACTOR_NAME, updates=base)]
    if consent.find_representative(data, party_id, state.actor_name) is None:
        step = _handoff(state, "caller is not a listed representative for this policyholder")
        step.updates.update(base)
        return [step]
    status = consent.check(data, state.consent_scenario, 0)
    if status == "approved":
        return [_consent_granted(party_id, checks=1)]
    if status == "timeout":
        return [_consent_timeout(state, checks=1)]
    return [Step(action=Action.REQUEST_CONSENT, params={"reason": consent.CONSENT_REASON},
                 updates={**base, "consent_status": "pending", "consent_checks": 1})]


def _consent_check(state: SessionState, data: InsuranceData) -> list[Step]:
    status = consent.check(data, state.consent_scenario, state.consent_checks)
    checks = state.consent_checks + 1
    if status == "approved":
        return [_consent_granted(state.pending_party_id, checks)]
    if status == "timeout":
        return [_consent_timeout(state, checks)]                                        # A-3 / S-2
    return [Step(action=Action.CONSENT_PENDING, params={"reason": consent.CONSENT_REASON},
                 updates={"consent_checks": checks})]


def _consent_granted(party_id: str, checks: int) -> Step:
    """Only now does the subject become reachable (D-2)."""
    return Step(action=Action.VERIFIED, transition=Phase.RESOLVE_INTENT, params={"representative": True},
                updates={"subject_party_id": party_id, "identity_locked": True, "consent_status": "approved",
                         "consent_checks": checks, "pending_party_id": None, "no_progress_turns": 0})


def _consent_timeout(state: SessionState, checks: int) -> Step:
    step = _handoff(state, "policyholder authorization timed out")
    step.updates.update({"consent_status": "timeout", "consent_checks": checks})
    return step


def _ladder(state: SessionState, ext: ExtractionResult, gate: str) -> tuple[int, dict] | None:
    """M-2..M-5: the persuasion ladder for a gate. Returns (level, state updates) when the ladder acts.

    L1 explain why, L2 offer alternatives (+ mention a human), L3 offer a human, L4 hand off.
    """
    level = state.escalation_level
    refusals = state.gate_refusals.get(gate, 0)
    gave_data = any(getattr(ext.identity, f) for f in PII_FIELDS)
    refused = ext.asks_to_skip or ext.refusal.target == gate
    upset = ext.emotion.intensity >= 2 and ext.emotion.type in ("frustration", "anger")
    updates: dict = {}

    if state.awaiting == Awaiting.HANDOFF_OFFER and ext.answer == "no" and not refused:
        updates.update({"escalation_level": 2, "handoff_offered": False, "awaiting": Awaiting.NOTHING})
        return 0, updates                                                  # declined the human: keep going

    if refused:
        refusals += 1
        updates["gate_refusals"] = {**state.gate_refusals, gate: refusals}
    if gave_data:
        level = max(level - 1, 0)                                          # M-4
    elif refused or upset:
        level = min(level + 1, 4)                                          # M-3

    if refusals >= 4:                                                      # M-5
        level = 4
    elif refusals >= 3:
        level = max(level, 3)
    if state.anger_streak >= 2 or state.no_progress_turns >= 4 or ext.emotion.distress:
        level = max(level, 3)

    if level == state.escalation_level and not refused and not updates:
        return None
    updates["escalation_level"] = level
    if gave_data and not refused:
        return 0, updates                                                  # progress: just keep asking
    return level, updates


# ---------------------------------------------------------------- RESOLVE_INTENT

def _summary(c: Claim) -> str:
    article = "an" if c.case_type[0] in "aeiou" else "a"
    return f"{c.case_id}, {article} {c.case_type} claim opened {human_date(c.created_at)} ({c.status})"


def _resolve_intent(state: SessionState, ext: ExtractionResult, data: InsuranceData, today: date,
                    entered: bool) -> list[Step]:
    repo = repo_for(state, data)
    assert repo is not None, "RESOLVE_INTENT requires a verified subject"

    if not entered and state.awaiting == Awaiting.CASE_CONFIRM and state.candidate_case_ids:
        if ext.answer == "yes":
            return [_resolved(state.candidate_case_ids[0])]
        if ext.answer == "no":
            return [Step(action=Action.ASK_INTENT,
                         updates={"candidate_case_ids": [], "case_query": CaseQuery(),
                                  "awaiting": Awaiting.NOTHING})]

    if not entered and ext.is_done and state.case_query.is_empty():                     # S-4
        return [Step(action=Action.TRANSITION, transition=Phase.POST_PROCESS)]

    res = case_resolver.resolve(repo, state.case_query, state.intent)
    if res.kind == "no_cases":
        return [Step(action=Action.NO_CASES_ON_FILE, transition=Phase.POST_PROCESS)]  # S-4
    if res.kind == "ask_intent":
        return [Step(action=Action.ASK_INTENT, updates={"awaiting": Awaiting.NOTHING})]
    if res.kind == "resolved":
        return [_resolved(res.case_ids[0])]
    claims = {c.case_id: c for c in repo.list_claims()}
    if res.kind == "confirm":
        return [Step(action=Action.CONFIRM_CASE, params={"summary": _summary(claims[res.case_ids[0]]) + "."},
                     updates={"candidate_case_ids": list(res.case_ids), "awaiting": Awaiting.CASE_CONFIRM})]
    if res.kind == "disambiguate":
        return [Step(action=Action.DISAMBIGUATE_CASE,
                     params={"summaries": [_summary(claims[i]) for i in res.case_ids]},
                     updates={"candidate_case_ids": list(res.case_ids), "awaiting": Awaiting.CASE_CHOICE})]
    everything = sorted(claims.values(), key=lambda c: c.created_at, reverse=True)
    return [Step(action=Action.NO_MATCHING_CASE,                                          # C-1 / C-6
                 params={"unknown_case_id": res.unknown_case_id,
                         "summaries": [_summary(c) for c in everything]},
                 updates={"case_query": CaseQuery(), "candidate_case_ids": [c.case_id for c in everything],
                          "awaiting": Awaiting.CASE_CHOICE})]


def _resolved(case_id: str) -> Step:
    return Step(action=Action.CASE_RESOLVED, transition=Phase.PROCESS_CASE,
                updates={"resolved_case_id": case_id, "candidate_case_ids": [], "case_presented": False,
                         "awaiting": Awaiting.NOTHING})


# ---------------------------------------------------------------- PROCESS_CASE

def _process_case(state: SessionState, ext: ExtractionResult, data: InsuranceData, today: date,
                  entered: bool) -> list[Step]:
    repo = repo_for(state, data)
    claim = repo.get_claim(state.resolved_case_id) if repo and state.resolved_case_id else None
    if claim is None:
        return [Step(action=Action.TRANSITION, transition=Phase.RESOLVE_INTENT)]
    facts = claim_facts(claim, data, today)

    if entered or not state.case_presented:
        must = [facts[k] for k in ("case", "status", "denial_reason", "documents_needed", "deadline") if k in facts]
        # only the paid amount up front: the other amounts are easy to misread as a payout (D-5)
        may = [f for k, f in facts.items() if f not in must and (f.kind != "amount" or k == "amount_net_pay")]
        return [Step(action=Action.PRESENT_CASE, must_state=must, may_state=may,
                     params={"pending_questions": state.pending_questions},
                     updates={"case_presented": True, "pending_questions": [],
                              "awaiting": Awaiting.ANYTHING_ELSE})]

    if ext.switch_case:                                                                  # S-5
        return [Step(action=Action.TRANSITION, transition=Phase.RESOLVE_INTENT,
                     updates={"resolved_case_id": None, "case_presented": False})]
    done = ext.is_done or ext.email_decision == "yes" or (
        state.awaiting == Awaiting.ANYTHING_ELSE and ext.answer == "no" and not ext.asks_question)
    if done:                                                                             # S-6
        return [Step(action=Action.TRANSITION, transition=Phase.POST_PROCESS)]
    return [_followup(claim, facts, ext.followup_topic, data, today)]


def _followup(claim: Claim, facts: dict, topic: str, data: InsuranceData, today: date) -> Step:
    """F-1..F-9: the topic's filled template must be said; claim facts may be used; nothing else (F-7)."""
    must, may = guidance.topic_facts(claim, topic, data, today)
    if topic == "submission_timing" and "deadline" in facts:                         # F-5 / F-6
        must.append(facts["deadline"])
    may += [f for f in facts.values() if f not in must]
    return Step(action=Action.ANSWER_FOLLOWUP, must_state=must, may_state=may,
                params={"topic": topic}, updates={"awaiting": Awaiting.ANYTHING_ELSE})


# ---------------------------------------------------------------- POST_PROCESS

def _post_process(state: SessionState, ext: ExtractionResult, data: InsuranceData, today: date,
                  entered: bool) -> list[Step]:
    email_masked = mask_email(on_file_email(state, data) or "")

    def offer() -> Step:
        return Step(action=Action.OFFER_EMAIL,
                    params={"email_masked": email_masked,
                            "to_policyholder": state.actor_type == "representative"},          # A-6
                    updates={"email_status": EmailStatus.OFFERED, "awaiting": Awaiting.EMAIL})

    def anything_else() -> Step:
        return Step(action=Action.ASK_ANYTHING_ELSE, updates={"awaiting": Awaiting.ANYTHING_ELSE})

    if entered:
        if state.discussed_facts and state.email_status == EmailStatus.NOT_OFFERED:      # P-2
            return [offer()]
        return [anything_else()]

    if ext.switch_case:                                                                  # S-8
        return [Step(action=Action.TRANSITION, transition=Phase.RESOLVE_INTENT,
                     updates={"resolved_case_id": None, "case_presented": False, "pending_followup": False})]

    decision = ext.email_decision
    if decision == "none" and state.awaiting == Awaiting.EMAIL and ext.answer != "none":
        decision = ext.answer
    if decision == "yes" and state.email_status != EmailStatus.SENT and state.discussed_facts:
        email = render_email(state, data)
        return [Step(action=Action.EMAIL_SENT, params={"email_masked": email_masked},
                     updates={"email_status": EmailStatus.SENT, "outbox": [*state.outbox, email]}),
                anything_else()]
    if decision == "no" and state.email_status in (EmailStatus.OFFERED, EmailStatus.NOT_OFFERED):
        return [Step(action=Action.EMAIL_SKIPPED, updates={"email_status": EmailStatus.DECLINED}),
                anything_else()]
    if decision == "unclear" and state.awaiting == Awaiting.EMAIL:                     # P-3
        if not state.email_reconfirmed:
            return [Step(action=Action.RECONFIRM_EMAIL, updates={"email_reconfirmed": True})]
        return [Step(action=Action.EMAIL_SKIPPED, updates={"email_status": EmailStatus.DECLINED}),
                anything_else()]

    if ext.asks_question and state.resolved_case_id:                                    # S-7
        repo = repo_for(state, data)
        claim = repo.get_claim(state.resolved_case_id)
        steps = [_followup(claim, claim_facts(claim, data, today), ext.followup_topic, data, today)]
        steps[0].updates["pending_followup"] = True
        steps[0].params["after_email_sent"] = state.email_status == EmailStatus.SENT     # P-7
        steps.append(offer() if state.email_status == EmailStatus.OFFERED else anything_else())  # P-8
        return steps

    finished = ext.is_done or (state.awaiting == Awaiting.ANYTHING_ELSE and ext.answer == "no")
    if finished:
        if state.email_status == EmailStatus.OFFERED:
            return [Step(action=Action.RECONFIRM_EMAIL, updates={"email_reconfirmed": True,
                                                                 "awaiting": Awaiting.EMAIL})]
        return [Step(action=Action.CLOSE, transition=Phase.COMPLETE,                    # S-9
                     updates={"awaiting": Awaiting.NOTHING})]
    if state.email_status == EmailStatus.OFFERED:
        return [offer()]
    return [anything_else()]
