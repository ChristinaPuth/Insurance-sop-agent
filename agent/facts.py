"""Grounded facts and the checks that decide what was really said (SPEC T-3, T-4, T-6, T-7)."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .data import Claim, InsuranceData
from .schemas import AgentReply, Directive, Fact

GENERIC_DOC_WORDS = {"report", "original", "treating", "provider"}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def human_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _doc_keywords(docs: tuple[str, ...]) -> tuple[str, ...]:
    out = []
    for doc in docs:
        words = [w for w in doc.lower().split() if w not in GENERIC_DOC_WORDS]
        out.append(" ".join(words) or doc.lower())
    return tuple(out)


def claim_facts(claim: Claim, data: InsuranceData, today: date) -> dict[str, Fact]:
    """Every statement the agent may make about one claim, keyed by kind."""
    cid = claim.case_id
    facts: dict[str, Fact] = {}

    def add(kind: str, value: str, source: str, keywords: tuple[str, ...], key: str | None = None) -> None:
        key = key or kind
        facts[key] = Fact(fact_id=f"{cid}:{key}", case_id=cid, kind=kind, value=value,
                          source=source, keywords=keywords)

    article = "an" if claim.case_type[0] in "aeiou" else "a"
    add("case", f"Claim {cid} is {article} {claim.case_type} claim opened on {human_date(claim.created_at)}.",
        f"claims.{cid}", (cid.lower(), f"date:{claim.created_at}"))
    add("status", f"The current status of claim {cid} is {claim.status} ({claim.summary.lower()}).",
        f"claims.{cid}.status", (claim.status,))
    if claim.denial_reason:
        add("denial_reason", f"It was denied because {claim.denial_reason}.",
            f"claims.{cid}.denial_reason", _doc_keywords(claim.documents_needed))
    if claim.documents_needed:
        docs = " and ".join(claim.documents_needed)
        add("documents_needed", f"To reconsider the claim, the review needs: {docs}.",
            f"claims.{cid}.documents_needed", _doc_keywords(claim.documents_needed))
    if claim.appeal_deadline:
        deadline = date.fromisoformat(claim.appeal_deadline)
        days = (deadline - today).days
        if days >= 0:                                                  # F-5
            value = (f"The appeal deadline is {human_date(claim.appeal_deadline)}, "
                     f"{days} days from today. Please submit the missing documents within a week, "
                     f"and no later than the deadline.")
        else:                                                          # F-6 takes priority
            value = (f"The appeal deadline on record was {human_date(claim.appeal_deadline)}, which has "
                     f"already passed. I can't promise an appeal or an extension; a representative can "
                     f"review whether any other options are available.")
        add("deadline", value, f"claims.{cid}.appeal_deadline", (f"date:{claim.appeal_deadline}",))

    schema = data.claim_schema.get("field_descriptions", {})
    for field in ("net_pay", "allowed_max_amount", "expected_reimbursement_amount", "net_fee"):
        desc = schema.get(field, {}).get("description", "")
        amount = getattr(claim, field)
        add("amount", f"{field.replace('_', ' ')}: ${amount} — {desc}",
            f"claims.{cid}.{field}", (f"money:{amount}",), key=f"amount_{field}")
    return facts


# ---------------------------------------------------------------- text scanning

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NAMED = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?!\d)(?:st|nd|rd|th)?"
                    r"(?:,?\s+(\d{4}))?", re.IGNORECASE)
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)|\b(\d[\d,]*\.\d{2})\b")


def dates_in(text: str) -> set[tuple[int, int, int | None]]:
    found: set[tuple[int, int, int | None]] = set()
    for y, m, d in _ISO.findall(text):
        found.add((int(m), int(d), int(y)))
    for mon, d, y in _NAMED.findall(text):
        found.add((MONTHS[mon[:3].lower()], int(d), int(y) if y else None))
    for m, d, y in _SLASH.findall(text):
        found.add((int(m), int(d), int(y)))
    return found


def money_in(text: str) -> set[Decimal]:
    out = set()
    for a, b in _MONEY.findall(text):
        try:
            out.add(Decimal((a or b).replace(",", "")))
        except InvalidOperation:
            pass
    return out


def _date_ok(found: tuple[int, int, int | None], allowed: set[tuple[int, int, int]]) -> bool:
    m, d, y = found
    return any(m == am and d == ad and (y is None or y == ay) for am, ad, ay in allowed)


def _allowed_dates(facts: list[Fact]) -> set[tuple[int, int, int]]:
    out = set()
    for f in facts:
        for k in f.keywords:
            if k.startswith("date:"):
                d = date.fromisoformat(k[5:])
                out.add((d.month, d.day, d.year))
    return out


def _allowed_money(facts: list[Fact]) -> set[Decimal]:
    return {Decimal(k[6:]) for f in facts for k in f.keywords if k.startswith("money:")}


def mentions(text: str, fact: Fact) -> bool:
    """T-3 ②: every keyword of the fact appears in the text."""
    low = text.lower()
    for k in fact.keywords:
        if k.startswith("date:"):
            d = date.fromisoformat(k[5:])
            if not any(_date_ok(x, {(d.month, d.day, d.year)}) for x in dates_in(text)):
                return False
        elif k.startswith("money:"):
            if Decimal(k[6:]) not in money_in(text):
                return False
        elif k not in low:
            return False
    return True


def _param_text(directive: Directive) -> str:
    """Code-built step parameters (e.g. candidate claim summaries) are grounded too."""
    parts: list[str] = []

    def walk(v) -> None:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    for step in directive.steps:
        walk(step.params)
    return " ".join(parts)


def numbers_ok(text: str, directive: Directive) -> list[str]:
    """T-6: every date and amount in the reply must equal an allowed fact or step-parameter value."""
    facts = directive.allowed_facts
    params = _param_text(directive)
    problems = []
    allowed_d = _allowed_dates(facts) | {d for d in dates_in(params) if d[2] is not None}
    for d in dates_in(text):
        if not _date_ok(d, allowed_d):
            problems.append(f"date {d} not in allowed facts")
    allowed_m = _allowed_money(facts) | money_in(params)
    for m in money_in(text):
        if m not in allowed_m:
            problems.append(f"amount {m} not in allowed facts")
    return problems


def facts_said(reply: AgentReply, directive: Directive) -> list[Fact]:
    """T-3: id must be allowed this turn AND its keywords must be in the text."""
    allowed = {f.fact_id: f for f in directive.allowed_facts}
    return [allowed[i] for i in dict.fromkeys(reply.used_fact_ids)
            if i in allowed and mentions(reply.text, allowed[i])]


def missing_must_state(said: list[Fact], directive: Directive) -> list[Fact]:
    ids = {f.fact_id for f in said}
    return [f for f in directive.must_state if f.fact_id not in ids]
