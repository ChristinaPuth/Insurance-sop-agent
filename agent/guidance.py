"""Follow-up answers from required_document_guideline.json (SPEC F-1 .. F-9, D-4).

The extractor classifies the topic; this module picks and fills the template. The LLM may only rephrase.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .data import Claim, InsuranceData
from .schemas import Fact

# extractor topic -> guideline "topic" key
TOPIC_KEYS = {
    "submission_timing": "submission_timing",
    "processing_time": "processing_time_after_submission",
    "submission_method": "submission_method",
    "file_format": "file_format_requirements",
    "receipt_confirmation": "receipt_confirmation",
}
TOPICS = tuple(TOPIC_KEYS)


def _words(s: str) -> set[str]:
    return set(s.lower().split())


def match_doc_key(doc: str, keys) -> str | None:
    """D-4: the case's document name matches a guideline key when all its words appear in the key."""
    want = _words(doc)
    return next((k for k in keys if k != "default" and want <= _words(k)), None)


def deadline_passed(claim: Claim, today: date) -> bool:
    return bool(claim.appeal_deadline) and today > date.fromisoformat(claim.appeal_deadline)


def _fact(claim: Claim, key: str, text: str, source: str) -> Fact:
    return Fact(fact_id=f"{claim.case_id}:guide_{key}", case_id=claim.case_id, kind="guidance",
                value=text, source=source)


def _fill(template: str, claim: Claim, settings: Mapping[str, Any]) -> str:
    docs = " and ".join(claim.documents_needed) or "the requested documents"
    avg = settings["average_processing_time_after_submission"]["en"]
    return (template.replace("{case_id}", claim.case_id).replace("{documents}", docs)
            .replace("{average_processing_time_after_submission}", avg))


def topic_facts(claim: Claim, topic: str, data: InsuranceData, today: date) -> tuple[list[Fact], list[Fact]]:
    """Returns (must_state, may_state) guidance facts for one follow-up topic."""
    g = data.guideline
    settings = g["claim_followup_settings"]
    by_topic = {t["topic"]: t for t in g["claim_followup_guidance"]}
    must: list[Fact] = []
    may: list[Fact] = []

    if topic == "doc_alternatives":                                                       # F-9
        alts = g["document_alternative_guidance"]
        for doc in claim.documents_needed:
            key = match_doc_key(doc, alts.keys())
            text = alts[key]["en"] if key else alts["default"]["en"]
            must.append(_fact(claim, f"alt_{doc.replace(' ', '_')}", text,
                              f"guideline.document_alternative_guidance.{key or 'default'}"))
        if claim.documents_needed:
            general = by_topic["missing_required_material_alternatives"]["en"]
            may.append(_fact(claim, "alt_general", _fill(general, claim, settings),
                             "guideline.claim_followup_guidance.missing_required_material_alternatives"))
        may.append(_fact(claim, "alt_human", settings["human_review_after_document_alternatives_exhausted"]["en"],
                         "guideline.claim_followup_settings.human_review_after_document_alternatives_exhausted"))
        return must, may

    if topic in TOPICS:
        entry = by_topic.get(TOPIC_KEYS[topic])
        if topic == "submission_timing" and deadline_passed(claim, today):              # F-6 beats F-5
            entry = None
        if entry and (not entry.get("requires_documents") or claim.documents_needed):
            must.append(_fact(claim, topic, _fill(entry["en"], claim, settings),
                              f"guideline.claim_followup_guidance.{entry['topic']}"))
        if topic in ("file_format", "submission_method") and claim.documents_needed:   # F-2
            docs = g["document_guidance"]
            for doc in claim.documents_needed:
                key = match_doc_key(doc, docs.keys())
                if key:
                    may.append(_fact(claim, f"doc_{doc.replace(' ', '_')}", docs[key]["en"],
                                     f"guideline.document_guidance.{key}"))
            by_type = g.get("case_type_guidance", {}).get(claim.case_type)
            if by_type:
                may.append(_fact(claim, "case_type", by_type["en"], f"guideline.case_type_guidance.{claim.case_type}"))
            may.append(_fact(claim, "default", g["default_guidance"]["en"], "guideline.default_guidance"))
        if must or may:
            return must, may

    # F-4: nothing specific -> the generic fallback, offered alongside the claim facts
    if claim.documents_needed:
        may.append(_fact(claim, "fallback", g["claim_followup_fallback"]["en"], "guideline.claim_followup_fallback"))
    return must, may
