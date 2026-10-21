import pytest

from agent import normalize
from agent.verification import fingerprint, verify

MARGARET = {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}


def test_three_matching_fields_verify(data):  # covers V-1
    r = verify(MARGARET, data.policyholders, "ssn")
    assert r.ok and r.party_id == "P9"


def test_two_fields_are_not_enough(data):  # covers V-1
    r = verify({"full_name": "Margaret Chen", "dob": "1985-03-15"}, data.policyholders)
    assert not r.ok


def test_policy_number_does_not_count(data):  # covers V-2
    r = verify({"full_name": "Margaret Chen", "dob": "1985-03-15"}, data.policyholders, policy_number="POL-9921")
    assert not r.ok


def test_all_wrong_fails(data):  # covers V-1
    r = verify({"full_name": "John Doe", "dob": "1970-01-01", "id_last4": "0000"}, data.policyholders)
    assert not r.ok


def test_three_right_one_wrong_fails(data):  # covers V-1 (no conflicts)
    claims = {**MARGARET, "email": "wrong@email.com"}
    assert not verify(claims, data.policyholders, "ssn").ok


def test_fields_from_different_people_fail(data):  # covers V-1 (same record)
    claims = {"full_name": "Margaret Chen", "dob": "1990-08-21", "phone": "+16505212830"}
    assert not verify(claims, data.policyholders).ok


def test_near_identical_phone_is_not_margaret(data):  # covers V-5
    claims = {"full_name": "Margaret Chen", "dob": "1985-03-15", "phone": "+16505212830"}
    assert not verify(claims, data.policyholders).ok


def test_national_id_holder_verifies(data):  # covers V-7
    claims = {"full_name": "Tian Ma", "dob": "1964-09-10", "id_last4": "6688"}
    r = verify(claims, data.policyholders, "national_id")
    assert r.ok and r.party_id == "P12"


def test_wrong_id_type_is_neither_match_nor_conflict(data):  # covers V-7
    claims = {"full_name": "Ma Tian", "dob": "1964-09-10", "id_last4": "6688"}
    r = verify(claims, data.policyholders, "ssn")
    assert not r.ok and r.type_mismatch
    claims["phone"] = "+16502088799"
    assert verify(claims, data.policyholders, "ssn").ok


def test_aliases_from_data(data):  # covers V-3, V-6, V-11
    claims = {"full_name": "Yaven Li", "email": "yawen.li@example.com", "dob": "1989-12-03"}
    r = verify(claims, data.policyholders)
    assert r.ok and r.party_id == "P13"


def test_fingerprint_changes_only_with_values():  # covers V-9
    a = fingerprint(MARGARET, "ssn")
    assert a == fingerprint(dict(reversed(list(MARGARET.items()))), "ssn")
    assert a != fingerprint({**MARGARET, "dob": "1985-03-16"}, "ssn")


@pytest.mark.parametrize("raw,expected", [
    ("1985-03-15", "1985-03-15"), ("March 15th, 1985", "1985-03-15"), ("03/15/1985", "1985-03-15"),
])
def test_dob_normalization(raw, expected):  # covers E-1
    assert normalize.dob(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("(650) 521-2836", "+16505212836"), ("650-521-2836", "+16505212836"), ("+1 650 521 2836", "+16505212836"),
])
def test_phone_normalization(raw, expected):  # covers E-1
    assert normalize.phone(raw) == expected


def test_dotenv_loading_never_overrides_env(tmp_path, monkeypatch):  # covers K-1
    from agent.config import load_dotenv
    env = tmp_path / ".env"
    env.write_text('# comment\nOPENAI_API_KEY="from-file"\nMODEL=m1\nOPENAI_BASE_URL=\nexport DEMO_TODAY=2026-02-15\n')
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DEMO_TODAY", raising=False)
    monkeypatch.setenv("MODEL", "from-shell")
    load_dotenv(env)
    import os
    assert os.environ["OPENAI_API_KEY"] == "from-file"
    assert os.environ["MODEL"] == "from-shell"          # real env wins
    assert "OPENAI_BASE_URL" not in os.environ          # empty values skipped
    assert os.environ["DEMO_TODAY"] == "2026-02-15"


def test_dotenv_edits_apply_without_restart(tmp_path, monkeypatch):  # covers K-1
    from agent.config import load_dotenv
    import os
    env = tmp_path / ".env"
    monkeypatch.delenv("SOP_TEST_MODEL", raising=False)
    env.write_text("SOP_TEST_MODEL=first\n")
    load_dotenv(env)
    assert os.environ["SOP_TEST_MODEL"] == "first"
    env.write_text("SOP_TEST_MODEL=second\n")
    load_dotenv(env)
    assert os.environ["SOP_TEST_MODEL"] == "second"            # edited value picked up
    env.write_text("# removed\n")
    load_dotenv(env)
    assert "SOP_TEST_MODEL" not in os.environ                   # removed line is dropped


def test_site_settings_win_then_env_then_defaults():  # covers K-1, K-2, K-3, U-7
    from agent.config import Settings
    from agent.llm_service import resolve_connection
    from pathlib import Path
    env = Settings(api_key="gsk_env", base_url=None, extract_model="openai/gpt-oss-20b",
                   response_model="openai/gpt-oss-20b", data_dir=Path("."), demo_today=None, model_configured=True)
    c = resolve_connection(env)
    assert (c.api_key, c.model, c.key_source) == ("gsk_env", "openai/gpt-oss-20b", ".env / environment")
    assert c.base_url == "https://api.groq.com/openai/v1"
    c = resolve_connection(env, typed_key="sk-site", typed_model="gpt-4.1-mini")
    assert (c.api_key, c.model, c.key_source, c.model_source) == ("sk-site", "gpt-4.1-mini", "site settings", "site settings")
    assert c.base_url is None                                   # sk- key: OpenAI
    bare = Settings(api_key="gsk_x", base_url=None, extract_model="gpt-4.1-mini", response_model="gpt-4.1-mini",
                    data_dir=Path("."), demo_today=None, model_configured=False)
    assert resolve_connection(bare).model == "openai/gpt-oss-120b"  # provider default only when nothing is set
