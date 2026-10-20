"""Persuasion ladder, de-escalation and scope wording (SPEC §9, §10)."""
from agent.schemas import Phase

from .conftest import GOLDEN, GOLDEN_EXT

REFUSE = {"refusal": {"target": "verification"}, "asks_to_skip": True,
          "emotion": {"type": "anger", "intensity": 2}}
LEAKS = ["cl-2048", "pathology", "office note", "1450", "march 18"]


def test_ladder_climbs_and_hands_off(run):  # covers M-2, M-5
    s, replies = run([("no", REFUSE)] * 4)
    steps = [t.steps[-1] for t in s.trace]
    assert steps == ["EXPLAIN_GATE", "OFFER_ALT_FIELDS", "OFFER_HANDOFF", "HANDOFF"]
    assert s.phase == Phase.HANDOFF
    assert all(not any(x in r.lower() for x in LEAKS) for r in replies)
    assert "representative" in replies[1]                                   # L2 mentions a human


def test_cooperation_steps_down(run):  # covers M-4
    s, _ = run([("no", REFUSE), ("no", REFUSE),
                ("ok fine, Margaret Chen", {"identity": {"full_name": "Margaret Chen"}})])
    assert s.escalation_level == 1 and s.trace[-1].steps == ["ASK_ID"]


def test_declining_the_human_keeps_verifying(run):  # covers M-2 L3 -> back to L2
    s, _ = run([("no", REFUSE)] * 3 + [("no, I'll verify", {"answer": "no"})])
    assert s.phase == Phase.VERIFY_ID and s.escalation_level == 2


def test_refusing_one_field_is_not_a_gate_refusal(run):  # covers M-6
    s, _ = run([("not my SSN", {"refusal": {"target": "field", "field": "id_last4"}})] * 3)
    assert s.gate_refusals == {} and s.phase == Phase.VERIFY_ID


def test_anger_twice_at_max_offers_human(run):  # covers M-5
    hot = {"emotion": {"type": "anger", "intensity": 3}}
    s, _ = run([("!!!", hot), ("!!!", hot)])
    assert s.trace[-1].steps == ["OFFER_HANDOFF"]


def test_distress_offers_human(run):  # covers M-5
    s, _ = run([("I can't afford this, I don't know what to do",
                 {"emotion": {"type": "anxiety", "intensity": 3, "distress": True}})])
    assert s.trace[-1].steps == ["OFFER_HANDOFF"]


def test_second_abuse_hands_off(run):  # covers M-5
    rude = {"emotion": {"type": "anger", "intensity": 3, "abusive": True}}
    s, _ = run([("you idiot", rude), ("useless idiot", rude)])
    assert s.phase == Phase.HANDOFF
    assert s.handoff.reason == "abusive language after de-escalation"


def test_ack_emotion_not_repeated(run):  # covers M-7
    upset = {"emotion": {"type": "frustration", "intensity": 2}, "identity": {"full_name": "Margaret Chen"}}
    s, _ = run([("ugh", upset), ("ugh", {**upset, "identity": {"dob": "1985-03-15"}})])
    assert "ACK_EMOTION" in s.trace[0].prefaces and "ACK_EMOTION" not in s.trace[1].prefaces


def test_out_of_role_redirects(run):  # covers O-1
    s, replies = run([("quote for car insurance?", {"off_topic": "out_of_role"})])
    assert s.off_topic_streak == 1 and "another team" in replies[0]


def test_non_english_is_not_counted(run):  # covers G-5
    s, replies = run([("你好，我想查理赔", {"off_topic": "non_english"})])
    assert s.off_topic_streak == 0 and "only assist in English" in replies[0]


def test_handoff_text_is_fixed(data):  # handoff wording never comes from the LLM
    from agent.llm_service import FakeLLM
    from agent.orchestrator import handle_turn, start_session
    from agent.schemas import AgentReply
    from .conftest import TODAY
    llm = FakeLLM([{"wants_human": True}], replies=[AgentReply(text="Sure thing!")])
    s, reply = handle_turn(start_session("SES-T"), "human please", llm, data, TODAY)
    assert s.handoff.reference in reply and "verify your identity" in reply
    assert llm.respond_contexts == []


def test_followup_after_email_sent_is_flagged(run):  # covers P-7
    s, replies = run([
        (GOLDEN, GOLDEN_EXT),
        ("that's all", {"is_done": True}),
        ("yes", {"email_decision": "yes"}),
        ("how do I submit?", {"asks_question": True, "followup_topic": "submission_method"}),
    ])
    assert "isn't included in the summary email" in replies[-1]
    assert len(s.outbox) == 1 and s.trace[-1].steps == ["ANSWER_FOLLOWUP", "ASK_ANYTHING_ELSE"]


def test_faq_answer_recorded_for_email(run):  # covers F-1 + P-5 Next steps
    s, replies = run([
        (GOLDEN, GOLDEN_EXT),
        ("How do I submit?", {"asks_question": True, "followup_topic": "submission_method"}),
        ("that's all", {"is_done": True}),
        ("yes", {"email_decision": "yes"}),
    ])
    assert "member portal" in replies[1]
    assert "member portal" in s.outbox[0].body
