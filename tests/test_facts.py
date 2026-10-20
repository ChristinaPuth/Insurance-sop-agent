from datetime import date

from agent.data import Claim
from agent.facts import claim_facts, facts_said, numbers_ok
from agent.schemas import AgentReply, Directive


def cl2048(data) -> Claim:
    return next(c for c in data.claims if c.case_id == "CL-2048")


def directive(data, today=date(2026, 2, 15)):
    facts = claim_facts(cl2048(data), data, today)
    d = Directive()
    d.must_state = [facts["status"], facts["deadline"]]
    d.may_state = [facts["amount_net_pay"]]
    return d, facts


def test_deadline_before_and_after(data):  # covers F-5, F-6
    before = claim_facts(cl2048(data), data, date(2026, 2, 15))["deadline"].value
    after = claim_facts(cl2048(data), data, date(2026, 10, 19))["deadline"].value
    assert "31 days" in before and "within a week" in before
    assert "already passed" in after and "within a week" not in after


def test_unknown_fact_ids_are_dropped(data):  # covers T-3 ①
    d, _ = directive(data)
    reply = AgentReply(text="It is denied.", used_fact_ids=["CL-2048:status", "CL-9999:made_up"])
    assert [f.fact_id for f in facts_said(reply, d)] == ["CL-2048:status"]


def test_claimed_fact_must_appear_in_text(data):  # covers T-3 ②
    d, _ = directive(data)
    reply = AgentReply(text="Your claim is under review.", used_fact_ids=["CL-2048:status", "CL-2048:deadline"])
    assert facts_said(reply, d) == []
    ok = AgentReply(text="It was denied. The deadline is March 18, 2026.",
                    used_fact_ids=["CL-2048:status", "CL-2048:deadline"])
    assert len(facts_said(ok, d)) == 2


def test_wrong_amount_or_date_is_rejected(data):  # covers T-6
    d, _ = directive(data)
    assert numbers_ok("The deadline is March 18, 2026 and we paid $0.00.", d) == []
    assert numbers_ok("You will receive $1,450.00.", d)        # allowed_max is not an allowed fact here
    assert numbers_ok("The deadline is March 28, 2026.", d)


def test_dates_from_step_params_are_allowed(data):  # covers T-6 (candidate lists)
    from agent.schemas import Action, Step
    d = Directive()
    d.add(Step(action=Action.DISAMBIGUATE_CASE,
               params={"summaries": ["CL-2102, an auto claim opened February 28, 2026 (open)"]}))
    assert numbers_ok("You have an auto claim from Feb 28, 2026.", d) == []
    assert numbers_ok("You have an auto claim from Feb 27, 2026.", d)
