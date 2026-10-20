from datetime import date

import pytest

from agent.guidance import match_doc_key, topic_facts

FEB, OCT = date(2026, 2, 15), date(2026, 10, 19)


def claim(data, cid):
    return next(c for c in data.claims if c.case_id == cid)


def test_doc_names_match_guideline_keys(data):  # covers D-4
    keys = data.guideline["document_guidance"].keys()
    assert match_doc_key("pathology report", keys) == "original pathology report"
    assert match_doc_key("office note", keys) == "treating provider office note"
    assert match_doc_key("diagnosis report", keys) is None


@pytest.mark.parametrize("topic,phrase", [
    ("submission_method", "member portal"),
    ("processing_time", "usually less than a week"),
    ("submission_timing", "within a week"),
    ("receipt_confirmation", "intake delay"),
    ("file_format", "clear, complete"),
])
def test_topics_fill_templates(data, topic, phrase):  # covers F-1
    must, _ = topic_facts(claim(data, "CL-2048"), topic, data, FEB)
    assert must and phrase in must[0].value
    assert "{" not in must[0].value and "CL-2048" in must[0].value
    assert "pathology report and office note" in must[0].value


def test_file_format_adds_document_specific_guidance(data):  # covers F-2
    _, may = topic_facts(claim(data, "CL-2048"), "file_format", data, FEB)
    sources = {f.source for f in may}
    assert "guideline.document_guidance.original pathology report" in sources
    assert "guideline.case_type_guidance.healthcare" in sources


def test_timing_template_dropped_after_deadline(data):  # covers F-6 over F-5
    must, may = topic_facts(claim(data, "CL-2048"), "submission_timing", data, OCT)
    assert not any("within a week" in f.value for f in must + may)


def test_doc_alternatives(data):  # covers F-9
    must, may = topic_facts(claim(data, "CL-2048"), "doc_alternatives", data, FEB)
    assert any("replacement copy" in f.value for f in must)
    assert any("human claims representative" in f.value for f in may)


def test_unknown_document_uses_default_alternative(data):  # covers D-4 fallback
    must, _ = topic_facts(claim(data, "CL-3001"), "doc_alternatives", data, FEB)
    assert must[0].source.endswith(".default")


def test_no_topic_falls_back(data):  # covers F-4
    must, may = topic_facts(claim(data, "CL-2048"), "none", data, FEB)
    assert not must and may[0].source == "guideline.claim_followup_fallback"


def test_every_extractor_topic_maps_to_a_guideline_entry(data):  # F-1
    from agent.guidance import TOPIC_KEYS
    topics = {t["topic"] for t in data.guideline["claim_followup_guidance"]}
    assert set(TOPIC_KEYS.values()) <= topics
