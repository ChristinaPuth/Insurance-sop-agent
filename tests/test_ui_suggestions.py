"""The UI's suggested caller replies follow the SOP state and never need claim data before verification."""
import ui
from agent.schemas import Awaiting, EmailStatus, Phase

from .conftest import GOLDEN, GOLDEN_EXT


def test_fresh_session_offers_identity_and_edge_cases(run):
    s, _ = run([("hi", {"off_topic": "smalltalk"})])
    out = ui.suggestions(s)
    assert out[0].startswith("My name is Margaret Chen") and "SSN last four 4472" in out[0]
    assert any("Just tell me why my claim was denied" in x for x in out)


def test_partial_identity_suggests_only_whats_missing(run):
    s, _ = run([("I'm Margaret Chen", {"identity": {"full_name": "Margaret Chen"}})])
    first = ui.suggestions(s)[0]
    assert "Margaret" not in first and "DOB 1985-03-15" in first and "4472" in first


def test_other_caller_gets_no_margaret_details(run):
    s, _ = run([("I'm Ava Lopez", {"identity": {"full_name": "Ava Lopez"}})])
    assert not any("1985" in x for x in ui.suggestions(s))


def test_processing_phase_offers_followups(run):
    s, _ = run([(GOLDEN, GOLDEN_EXT)])
    out = ui.suggestions(s, claim_has_documents=True)
    assert "How do I submit the documents?" in out and "No, that's all." in out


def test_email_offer_and_terminal_states(run):
    s, _ = run([(GOLDEN, GOLDEN_EXT), ("that's all", {"is_done": True})])
    assert s.awaiting == Awaiting.EMAIL and "Yes, please send it." in ui.suggestions(s)
    declined = s.model_copy(update={"email_status": EmailStatus.DECLINED, "awaiting": Awaiting.ANYTHING_ELSE})
    assert ui.suggestions(declined)[0] == "Actually, please email me the summary."
    assert ui.suggestions(s.model_copy(update={"phase": Phase.COMPLETE})) == []


def test_consent_pending_suggestions(run):
    from .test_consent import DAVID, DAVID_EXT, session
    s, _ = run([(DAVID, DAVID_EXT)], state=session())
    assert ui.suggestions(s)[0] == "She says she approved it."
