"""Representative calls: actor / subject / authorization (SPEC §6)."""
from agent.orchestrator import start_session
from agent.schemas import EmailStatus, Phase

from .conftest import GOLDEN, GOLDEN_EXT

DAVID = ("Hi, I'm David Chen, calling for my mother Margaret Chen. Her DOB is 1985-03-15 and SSN last four 4472. "
         "It's about her denied healthcare claim from January.")
DAVID_EXT = {
    "caller_role": "representative", "actor_name": "David Chen",
    "identity": {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472", "id_type_stated": "ssn"},
    "intent": "denial_question", "case_hint": {"case_type": "healthcare", "status": "denied", "month": 1},
}
LEAKS = ["cl-2048", "pathology", "office note", "1450", "march 18"]


def session(scenario="default"):
    s = start_session("SES-REP")
    s.consent_scenario = scenario
    return s


def test_representative_waits_for_consent_then_gets_the_claim(run):  # covers A-2, A-3, D-2
    s, replies = run([(DAVID, DAVID_EXT), ("ok, she approved it", {"answer": "yes"})], state=session())
    first = s.trace[0]
    assert first.steps == ["REQUEST_CONSENT"] and first.phase_after == Phase.VERIFY_ID
    assert not any(t in replies[0].lower() for t in LEAKS)             # nothing before authorization
    assert s.trace[1].steps[:3] == ["VERIFIED", "CASE_RESOLVED", "PRESENT_CASE"]
    assert s.subject_party_id == "P9" and s.consent_status == "approved" and s.actor_type == "representative"
    assert "CL-2048" in replies[1]


def test_subject_is_not_reachable_while_pending(run):  # covers D-2
    s, _ = run([(DAVID, DAVID_EXT)], state=session())
    assert s.consent_status == "pending" and s.pending_party_id == "P9" and s.subject_party_id is None


def test_consent_timeout_hands_off(run):  # covers A-3, S-2
    turns = [(DAVID, DAVID_EXT)] + [("any update?", {})] * 4
    s, replies = run(turns, state=session("timeout"))
    assert [t.steps[-1] for t in s.trace] == ["REQUEST_CONSENT"] + ["CONSENT_PENDING"] * 3 + ["HANDOFF"]
    assert s.phase == Phase.HANDOFF and s.consent_status == "timeout"
    assert s.handoff.internal_summary["verified"] is False
    assert not any(t in r.lower() for r in replies for t in LEAKS)


def test_unlisted_caller_is_handed_off(run):  # covers A-2
    ext = {**DAVID_EXT, "actor_name": "Kevin Smith"}
    s, replies = run([(DAVID.replace("David Chen", "Kevin Smith"), ext)], state=session())
    assert s.phase == Phase.HANDOFF and s.subject_party_id is None
    assert not any(t in replies[0].lower() for t in LEAKS)


def test_missing_caller_name_is_asked(run):  # covers A-2
    ext = {**DAVID_EXT, "actor_name": None}
    s, replies = run([("calling for my mother...", ext), ("I'm David Chen", {"actor_name": "David Chen"})],
                     state=session())
    assert s.trace[0].steps == ["ASK_ACTOR_NAME"] and s.trace[1].steps == ["REQUEST_CONSENT"]


def test_caller_name_does_not_count_as_subject_pii(run):  # covers A-2
    ext = {"caller_role": "representative", "actor_name": "David Chen",
           "identity": {"full_name": "David Chen", "dob": "1985-03-15", "id_last4": "4472"}}
    s, _ = run([("I'm David Chen, DOB 1985-03-15, SSN 4472", ext)], state=session())
    assert s.subject_party_id is None and s.pending_party_id is None and s.verify_failures == 1


def test_email_goes_to_policyholder(run):  # covers A-6
    s, replies = run([(DAVID, DAVID_EXT), ("approved", {"answer": "yes"}),
                      ("that's all", {"is_done": True}), ("yes", {"email_decision": "yes"})], state=session())
    assert "policyholder's email" in replies[2]
    assert s.email_status == EmailStatus.SENT and s.outbox[0].to_masked.endswith("@email.com")


def test_policyholder_turning_into_representative_after_verification(run):  # covers A-4
    s, _ = run([(GOLDEN, GOLDEN_EXT), ("actually I'm her son", {"caller_role": "representative"})])
    assert s.phase == Phase.HANDOFF
    assert s.handoff.reason == "caller identity changed after verification"


def test_switching_to_representative_before_verification_keeps_fields(run):  # covers A-4
    s, _ = run([
        ("Margaret Chen, DOB 1985-03-15", {"identity": {"full_name": "Margaret Chen", "dob": "1985-03-15"}}),
        ("Sorry, I'm actually her son David Chen. Her SSN ends 4472.",
         {"caller_role": "representative", "actor_name": "David Chen", "identity": {"id_last4": "4472"}}),
    ], state=session())
    assert s.actor_type == "representative" and s.trace[-1].steps == ["REQUEST_CONSENT"]
