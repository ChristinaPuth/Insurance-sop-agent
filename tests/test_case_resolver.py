from agent.case_resolver import resolve
from agent.claims import ClaimsRepo
from agent.schemas import Intent
from agent.state import CaseQuery


def repo(data, party="P9"):
    return ClaimsRepo(data, party)


def test_specific_unique_hint_resolves(data):  # covers C-3
    r = resolve(repo(data), CaseQuery(case_type="healthcare", status="denied", month=1), Intent.STATUS_INQUIRY)
    assert r.kind == "resolved" and r.case_ids == ("CL-2048",)


def test_month_without_status_is_ambiguous(data):  # covers C-5: recency never picks
    r = resolve(repo(data), CaseQuery(case_type="healthcare", month=1), Intent.STATUS_INQUIRY)
    assert r.kind == "disambiguate" and set(r.case_ids) == {"CL-2048", "CL-2011"}
    assert r.case_ids[0] == "CL-2048"   # most recent first, but still a question


def test_vague_single_candidate_is_confirmed(data):  # covers C-4
    r = resolve(repo(data), CaseQuery(case_type="auto"), Intent.STATUS_INQUIRY)
    assert r.kind == "confirm" and r.case_ids == ("CL-2102",)


def test_no_clue_and_no_intent_asks(data):  # covers C-4
    assert resolve(repo(data), CaseQuery(), None).kind == "ask_intent"


def test_vague_intent_with_many_claims_disambiguates(data):  # covers C-4/C-5
    assert resolve(repo(data), CaseQuery(), Intent.STATUS_INQUIRY).kind == "disambiguate"


def test_claim_id_of_someone_else_is_not_found(data):  # covers C-1, D-2
    r = resolve(repo(data), CaseQuery(case_id="CL-3001"), Intent.STATUS_INQUIRY)
    assert r.kind == "no_match" and r.unknown_case_id == "CL-3001"


def test_own_claim_id_resolves(data):  # covers C-1
    assert resolve(repo(data), CaseQuery(case_id="cl-2102"), None).case_ids == ("CL-2102",)


def test_no_cases_on_file(data):  # covers C-6
    assert resolve(repo(data, "P7"), CaseQuery(status="denied"), Intent.STATUS_INQUIRY).kind == "no_cases"


def test_repo_never_exposes_other_parties(data):  # covers D-2
    r = repo(data)
    assert all(c.party_id == "P9" for c in r.list_claims())
    assert r.get_claim("CL-3001") is None


def test_denial_question_alone_narrows_to_denied(data):  # covers C-2, C-4
    r = resolve(repo(data), CaseQuery(), Intent.DENIAL_QUESTION)
    assert r.kind == "confirm" and r.case_ids == ("CL-2048",)
