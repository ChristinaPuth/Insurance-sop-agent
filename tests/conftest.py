from datetime import date

import pytest

from agent.config import ROOT
from agent.data import load_data
from agent.llm_service import FakeLLM
from agent.orchestrator import handle_turn, start_session

TODAY = date(2026, 2, 15)
GOLDEN = ("I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied "
          "healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.")
GOLDEN_EXT = {
    "identity": {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472", "id_type_stated": "ssn"},
    "policy_number": "POL-9921", "caller_role": "policyholder", "intent": "denial_question",
    "case_hint": {"case_type": "healthcare", "status": "denied", "month": 1},
}


@pytest.fixture(scope="session")
def data():
    return load_data(ROOT / "insurance_claims" / "fixtures")


@pytest.fixture
def run(data):
    """Run scripted turns: [(message, extraction_dict), ...] -> (final_state, replies)."""
    def _run(turns, today=TODAY, state=None):
        llm = FakeLLM([ext for _, ext in turns])
        s = state or start_session("SES-TEST")
        replies = []
        for msg, _ in turns:
            s, reply = handle_turn(s, msg, llm, data, today)
            replies.append(reply)
        return s, replies
    return _run
