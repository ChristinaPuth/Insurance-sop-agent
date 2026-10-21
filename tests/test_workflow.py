"""End-to-end SOP behaviour with scripted extractions (FakeLLM) and fallback text."""
from agent.llm_service import FakeLLM
from agent.orchestrator import handle_turn, start_session
from agent.schemas import AgentReply, EmailStatus, Phase

from .conftest import GOLDEN, GOLDEN_EXT, TODAY

LEAK_TERMS = ["cl-2048", "pathology", "office note", "1450", "march 18"]


def no_leak(text: str) -> bool:
    return not any(t in text.lower() for t in LEAK_TERMS)


def test_golden_path(run):  # covers S-1, S-3, S-12, C-3, P-2, P-5, S-9
    s, replies = run([
        (GOLDEN, GOLDEN_EXT),
        ("No, that's all.", {"answer": "no", "is_done": True}),
        ("Yes please.", {"email_decision": "yes", "answer": "yes"}),
        ("No, bye.", {"answer": "no", "is_done": True}),
    ])
    first = s.trace[0]
    assert first.steps[:3] == ["VERIFIED", "CASE_RESOLVED", "PRESENT_CASE"]
    assert first.phase_after == Phase.PROCESS_CASE
    assert "CL-2048" in replies[0] and "pathology" in replies[0]
    assert "how can i help" not in replies[0].lower()                 # did not ask from scratch
    assert "email" in replies[1].lower()
    assert s.email_status == EmailStatus.SENT and len(s.outbox) == 1
    assert "CL-2048" in s.outbox[0].body and "Amounts discussed" not in s.outbox[0].body
    assert s.phase == Phase.COMPLETE


def test_history_is_masked(run):  # covers X-1
    s, _ = run([(GOLDEN, GOLDEN_EXT)])
    user_text = next(t.text for t in s.history if t.role == "user")
    for raw in ("Margaret Chen", "1985-03-15", "4472"):
        assert raw not in user_text


def test_hint_remembered_but_nothing_disclosed_before_verification(run):  # covers E-3, C-8
    s, replies = run([
        ("Hi, I'm calling about my denied healthcare claim from January. I'm Margaret Chen.",
         {"identity": {"full_name": "Margaret Chen"}, "intent": "denial_question",
          "case_hint": {"case_type": "healthcare", "status": "denied", "month": 1}}),
    ])
    assert s.phase == Phase.VERIFY_ID and not s.verified
    assert s.case_query.status == "denied" and s.case_query.month == 1
    assert no_leak(replies[0])
    assert "2 more items" in replies[0]


def test_angry_caller_is_not_let_through(run):  # covers M-2, M-8, E-4
    s, replies = run([
        ("I'm Margaret Chen.", {"identity": {"full_name": "Margaret Chen"}}),
        ("I already told you who I am. This is ridiculous. Just tell me why my claim was denied.",
         {"intent": "denial_question", "asks_to_skip": True, "asks_question": True,
          "emotion": {"type": "frustration", "intensity": 3}}),
    ])
    assert s.phase == Phase.VERIFY_ID
    assert s.trace[-1].steps == ["EXPLAIN_GATE"] and "ACK_EMOTION" in s.trace[-1].prefaces
    assert no_leak(replies[-1]) and "protects you" in replies[-1]
    assert len(s.pending_questions) == 1                               # E-4


def test_pending_question_answered_after_verification(run):  # covers E-4
    s, _ = run([
        ("Why was my claim denied? I'm Margaret Chen.",
         {"identity": {"full_name": "Margaret Chen"}, "asks_question": True, "intent": "denial_question"}),
        ("DOB 1985-03-15, SSN 4472, it's the denied healthcare one",
         {"identity": {"dob": "1985-03-15", "id_last4": "4472", "id_type_stated": "ssn"},
          "case_hint": {"case_type": "healthcare", "status": "denied"}}),
    ])
    assert s.phase == Phase.PROCESS_CASE and s.resolved_case_id == "CL-2048"
    assert s.pending_questions == []


def test_failed_attempts_count_once_per_new_attempt(run):  # covers V-9, V-10, S-2
    wrong = {"identity": {"full_name": "Margaret Chen", "dob": "1985-03-15", "phone": "650-521-2830"}}
    s, replies = run([("...", wrong), ("same again", {}), ("same again", {})])
    assert s.verify_failures == 1 and s.phase == Phase.VERIFY_ID
    assert "couldn't verify" in replies[0] and "phone" not in replies[0].split("field")[0]

    s, _ = run([
        ("...", wrong),
        ("...", {"identity": {"phone": "650-521-2831"}}),
        ("...", {"identity": {"phone": "650-521-2832"}}),
    ])
    assert s.verify_failures == 3 and s.phase == Phase.HANDOFF
    assert s.handoff.internal_summary["verified"] is False
    assert "1985" not in str(s.handoff.internal_summary)                # H-3: no PII values


def test_ambiguous_month_asks_which_claim(run):  # covers C-5
    s, replies = run([
        ("...", {"identity": {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"},
                 "case_hint": {"case_type": "healthcare", "month": 1}}),
        ("the 2026 one", {"case_hint": {"year": 2026}}),
    ])
    assert s.trace[0].steps[-1] == "DISAMBIGUATE_CASE"
    assert "CL-2048" in replies[0] and "CL-2011" in replies[0]
    assert s.resolved_case_id == "CL-2048"


def test_other_persons_claim_id(run):  # covers C-1
    s, replies = run([
        ("...", {"identity": {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"},
                 "case_hint": {"case_id": "CL-3001"}}),
    ])
    assert s.phase == Phase.RESOLVE_INTENT
    assert "can't find claim CL-3001 on your account" in replies[0]
    assert "healthcare claim opened March 1" not in replies[0]


def test_no_cases_ends_without_email(run):  # covers S-4, P-2, S-9
    s, replies = run([
        ("...", {"identity": {"full_name": "Ava Lopez", "dob": "1990-08-21", "id_last4": "9180"},
                 "intent": "status_inquiry"}),
        ("no that's it", {"answer": "no", "is_done": True}),
    ])
    assert "don't see any claims" in replies[0]
    assert s.email_status == EmailStatus.NOT_OFFERED and s.phase == Phase.COMPLETE


def test_decline_then_change_mind(run):  # covers P-1
    s, _ = run([
        (GOLDEN, GOLDEN_EXT),
        ("that's all", {"is_done": True}),
        ("no email", {"email_decision": "no"}),
        ("actually, please send it", {"email_decision": "yes"}),
        ("bye", {"is_done": True}),
    ])
    assert s.email_status == EmailStatus.SENT and s.phase == Phase.COMPLETE


def test_followup_while_email_offered_reasks(run):  # covers S-7, P-8
    s, replies = run([
        (GOLDEN, GOLDEN_EXT),
        ("that's all", {"is_done": True}),
        ("Actually, how long does review take?", {"asks_question": True, "followup_topic": "processing_time"}),
    ])
    assert s.phase == Phase.POST_PROCESS and s.pending_followup
    assert s.trace[-1].steps == ["ANSWER_FOLLOWUP", "OFFER_EMAIL"]


def test_off_topic_offer_then_handoff(run):  # covers O-1, O-3, S-10
    rl = {"off_topic": "unrelated"}
    s, replies = run([("what is RL?", rl), ("and SGD?", rl), ("and Adam?", rl)])
    assert s.phase == Phase.VERIFY_ID and s.trace[-1].steps == ["OFFER_HANDOFF"]
    s2, _ = run([("no thanks, my name is Margaret Chen",
                  {"answer": "no", "identity": {"full_name": "Margaret Chen"}})], state=s)
    assert s2.off_topic_streak == 0 and s2.phase == Phase.VERIFY_ID
    s3, _ = run([("what is a transformer?", rl)], state=s)
    assert s3.phase == Phase.HANDOFF


def test_smalltalk_is_not_counted(run):  # covers O-1
    s, _ = run([("thanks!", {"off_topic": "smalltalk"})])
    assert s.off_topic_streak == 0


def test_wants_human_is_immediate(run):  # covers H-1
    s, replies = run([("let me talk to a person", {"wants_human": True})])
    assert s.phase == Phase.HANDOFF and "verify your identity" in replies[0]


def test_refused_field_offers_alternatives(run):  # covers M-6
    s, replies = run([("I won't give my SSN", {"refusal": {"target": "field", "field": "id_last4"}})])
    assert s.trace[-1].steps == ["OFFER_ALT_FIELDS"] and "SSN" not in replies[0]


def test_llm_reply_with_wrong_amount_falls_back(data):  # covers T-6
    bad = AgentReply(text="Good news, you'll get $1,450.00!", used_fact_ids=["CL-2048:status"])
    llm = FakeLLM([GOLDEN_EXT], replies=[bad])
    s, reply = handle_turn(start_session("SES-T"), GOLDEN, llm, data, TODAY)
    assert "1,450" not in reply and "pathology" in reply
    assert any("reply rejected" in n for n in s.trace[-1].notes)


def test_llm_reply_missing_must_state_gets_appended(data):  # covers T-4
    short = AgentReply(text="Thanks Margaret, you're verified. Your claim CL-2048 was denied.",
                       used_fact_ids=["CL-2048:status"])
    llm = FakeLLM([GOLDEN_EXT], replies=[short])
    s, reply = handle_turn(start_session("SES-T"), GOLDEN, llm, data, TODAY)
    assert "March 18, 2026" in reply and "pathology" in reply
    assert "CL-2048:deadline" in [f.fact_id for f in s.discussed_facts]


def test_pre_verification_reply_leak_is_blocked(data):  # covers X-4
    leaky = AgentReply(text="Your claim CL-2048 was denied for a missing pathology report.")
    llm = FakeLLM([{"identity": {"full_name": "Margaret Chen"}}], replies=[leaky])
    s, reply = handle_turn(start_session("SES-T"), "I'm Margaret Chen", llm, data, TODAY)
    assert no_leak(reply) and any("pre-verification" in n for n in s.trace[-1].notes)


def test_input_state_is_not_mutated(data):  # covers G-4
    s0 = start_session("SES-T")
    snapshot = s0.model_dump()
    handle_turn(s0, GOLDEN, FakeLLM([GOLDEN_EXT]), data, TODAY)
    assert s0.model_dump() == snapshot


def test_extraction_failure_clarifies(data):  # covers T-1
    s, reply = handle_turn(start_session("SES-T"), "hello", FakeLLM([]), data, TODAY)
    assert s.phase == Phase.VERIFY_ID and "rephrase" in reply


def test_rejected_key_reports_setup_problem(data):  # covers T-9
    from agent.llm_service import LLMError, default_base_url

    class BadKeyLLM(FakeLLM):
        def extract(self, message, context):
            raise LLMError("API call failed (AuthenticationError, 401)", config_problem=True)

    s, reply = handle_turn(start_session("SES-T"), GOLDEN, BadKeyLLM([]), data, TODAY)
    assert reply.startswith("[Setup problem]") and s.phase == Phase.VERIFY_ID
    assert default_base_url("gsk_abc") == "https://api.groq.com/openai/v1"
    assert default_base_url("sk-abc") is None


def test_rate_limit_asks_to_resend(data):  # covers T-9
    from agent.llm_service import LLMError

    class BusyLLM(FakeLLM):
        def extract(self, message, context):
            raise LLMError("API call failed (RateLimitError, 429)", rate_limited=True)

    s, reply = handle_turn(start_session("SES-T"), GOLDEN, BusyLLM([]), data, TODAY)
    assert "busy" in reply and "rephrase" not in reply and s.phase == Phase.VERIFY_ID


def test_other_persons_claim_after_verification(run):  # covers A-5
    s, replies = run([
        (GOLDEN, GOLDEN_EXT),
        ("Can you also check my son David's claim?", {"about_other_person": True, "asks_question": True}),
    ])
    assert s.trace[-1].steps == ["OTHER_PERSON_LOCKED"]
    assert s.subject_party_id == "P9" and s.resolved_case_id == "CL-2048" and s.phase == Phase.PROCESS_CASE
    assert "only access claims" in replies[-1]


def test_followup_context_carries_the_question(data):  # covers T-8, F-7
    llm = FakeLLM([GOLDEN_EXT, {"asks_question": True}])
    s, _ = handle_turn(start_session("SES-T"), GOLDEN, llm, data, TODAY)
    handle_turn(s, "Which doctor reviewed my claim?", llm, data, TODAY)
    assert llm.respond_contexts[-1]["CALLER_LATEST_MESSAGE"] == "Which doctor reviewed my claim?"


def test_other_person_keyword_safety_net(run):  # covers A-5, E-7
    s, replies = run([
        (GOLDEN, GOLDEN_EXT),
        ("Can you also check my son David's claim?", {"asks_question": True}),
    ])
    assert s.trace[-1].steps == ["OTHER_PERSON_LOCKED"] and "only access claims" in replies[-1]


def test_other_person_rule_ignores_own_claims():  # covers E-7
    from agent.orchestrator import mentions_other_person
    assert mentions_other_person("what about my wife's policy?")
    assert mentions_other_person("is there a claim for my daughter?")
    assert not mentions_other_person("can you check my auto claim?")
    assert not mentions_other_person("my son was in the car when the accident happened")


def test_off_topic_question_is_not_made_relevant_by_being_a_question(run):  # O-1
    rl = {"off_topic": "unrelated", "asks_question": True}
    s, _ = run([("what is RL?", rl), ("what is SGD?", rl), ("what is Adam?", rl)])
    assert s.trace[-1].steps == ["OFFER_HANDOFF"] and s.off_topic_streak == 3


def test_refused_field_keyword_safety_net(run):  # covers M-6, E-7
    s, replies = run([("I'm Margaret Chen but I don't want to give my SSN.",
                       {"identity": {"full_name": "Margaret Chen"}})])
    assert s.trace[-1].steps == ["OFFER_ALT_FIELDS"] and "SSN" not in replies[0]


def test_refused_field_rule():  # covers E-7
    from agent.orchestrator import refused_field
    assert refused_field("I don't want to give my SSN") == "id_last4"
    assert refused_field("I'd rather not share my phone number") == "phone"
    assert refused_field("my SSN ends in 4472") is None


def test_refused_field_name_from_model_is_normalized(run):  # M-6, E-7: model said "ssn" or left the field empty
    for field in ("ssn", None, "SSN last 4"):
        s, replies = run([("I'm Margaret Chen but I don't want to give my SSN.",
                           {"identity": {"full_name": "Margaret Chen"},
                            "refusal": {"target": "field", "field": field}})])
        assert s.trace[-1].steps == ["OFFER_ALT_FIELDS"], field
        assert "SSN" not in replies[0]


def test_field_refusal_tagged_as_verification_refusal(run):  # M-6, E-7: model over-reads one field as all
    s, replies = run([("I'm Margaret Chen but I don't want to give my SSN.",
                       {"identity": {"full_name": "Margaret Chen"},
                        "refusal": {"target": "verification"}})])
    assert s.trace[-1].steps == ["OFFER_ALT_FIELDS"] and s.gate_refusals == {}


def test_field_refusal_beats_a_skip_flag(run):  # M-6: model flagged both "skip" and one named field
    s, _ = run([("I'm Margaret Chen but I don't want to give my SSN.",
                 {"identity": {"full_name": "Margaret Chen"}, "asks_to_skip": True,
                  "refusal": {"target": "field", "field": "id_last4"}})])
    assert s.trace[-1].steps == ["OFFER_ALT_FIELDS"] and s.gate_refusals == {}


def test_question_during_email_offer_is_answered_even_if_read_as_unclear(run):  # S-7, P-8
    s, _ = run([
        (GOLDEN, GOLDEN_EXT),
        ("That's all.", {"is_done": True}),
        ("Actually, one more question: where do I upload the files?",
         {"asks_question": True, "followup_topic": "submission_method", "email_decision": "unclear"}),
    ])
    assert s.trace[-1].steps == ["ANSWER_FOLLOWUP", "OFFER_EMAIL"] and not s.email_reconfirmed


def test_setup_errors_say_what_to_fix(data):  # covers T-9
    from agent.llm_service import LLMError

    def bad(status):
        class Bad(FakeLLM):
            def extract(self, message, context):
                raise LLMError(f"API call failed ({status})", config_problem=True, status=status)
        return Bad([])

    _, model_reply = handle_turn(start_session("SES-T"), GOLDEN, bad(404), data, TODAY)
    _, key_reply = handle_turn(start_session("SES-T"), GOLDEN, bad(401), data, TODAY)
    assert "model name" in model_reply and "openai/gpt-oss-120b" in model_reply
    assert "API key was rejected" in key_reply


def test_groq_model_name_without_prefix_is_corrected():  # covers K-3
    from pathlib import Path
    from agent.config import Settings
    from agent.llm_service import resolve_connection
    s = Settings(api_key="gsk_x", base_url=None, extract_model="gpt-4.1-mini", response_model="gpt-4.1-mini",
                 data_dir=Path("."), demo_today=None, model_configured=False)
    c = resolve_connection(s, typed_model="gpt-oss-20b")
    assert c.model == "openai/gpt-oss-20b" and "corrected" in c.model_source
    assert resolve_connection(s, typed_key="sk-x", typed_model="gpt-oss-20b").model == "gpt-oss-20b"  # not Groq
