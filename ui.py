"""Presentation helpers for the Streamlit UI: CSS and small HTML blocks. No business logic here.

Everything interpolated into HTML is escaped; conversation text is never rendered through these helpers.
"""
from __future__ import annotations

from html import escape

from agent.schemas import EmailStatus, Phase
from agent.state import SessionState

STEPS = [
    (Phase.VERIFY_ID, "Verify identity"),
    (Phase.RESOLVE_INTENT, "Resolve intent"),
    (Phase.PROCESS_CASE, "Process claim"),
    (Phase.POST_PROCESS, "Follow-up"),
]

FIELD_NAMES = {"full_name": "Name", "dob": "Date of birth", "phone": "Phone", "email": "Email",
               "id_last4": "ID last 4"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --navy: #0B1F3A; --navy-2: #13294B; --ink: #0B1F3A; --muted: #5B6B82; --line: #E2E8F0;
  --teal: #0E9384; --teal-soft: #E6F6F4; --amber: #B45309; --amber-soft: #FEF3E2;
  --red: #B42318; --red-soft: #FDECEA; --surface: #FFFFFF; --canvas: #F5F7FA;
}
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button p, .stApp h1, .stApp h2, .stApp h3 {
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}

/* chrome */
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], [data-testid="stDecoration"], footer { display: none !important; }
.block-container { max-width: 1040px; padding-top: 1.4rem; padding-bottom: 7rem; }

/* header */
.app-header { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  flex-wrap: wrap; margin-bottom: 18px; }
.brand { display: flex; align-items: center; gap: 12px; }
.brand-mark { width: 40px; height: 40px; border-radius: 10px; background: var(--navy);
  display: grid; place-items: center; flex: none; }
.brand h1 { font-size: 1.2rem; font-weight: 700; margin: 0; padding: 0; color: var(--ink); line-height: 1.2; }
.brand p { margin: 2px 0 0; color: var(--muted); font-size: .85rem; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { font-size: .75rem; color: var(--muted); background: var(--surface); border: 1px solid var(--line);
  border-radius: 999px; padding: 4px 10px; white-space: nowrap; }
.chip b { color: var(--ink); font-weight: 600; }
.chip.live::before { content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: var(--teal); margin-right: 6px; vertical-align: 1px; }
.chip.off::before { content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #94A3B8; margin-right: 6px; vertical-align: 1px; }

/* stepper */
.stepper { display: flex; align-items: center; background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; padding: 12px 16px; gap: 6px; flex-wrap: wrap; }
.step { display: flex; align-items: center; gap: 8px; font-size: .82rem; color: var(--muted);
  font-weight: 500; white-space: nowrap; }
.dot { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-size: .72rem;
  font-weight: 700; border: 1.5px solid #CBD5E1; color: #94A3B8; background: var(--surface); flex: none; }
.step.done .dot { background: var(--teal); border-color: var(--teal); color: #fff; }
.step.done { color: var(--ink); }
.step.current .dot { border-color: var(--teal); color: var(--teal); box-shadow: 0 0 0 4px var(--teal-soft); }
.step.current { color: var(--ink); font-weight: 600; }
.step.stopped .dot { border-color: var(--red); color: var(--red); background: var(--red-soft); }
.step.stopped { color: var(--red); font-weight: 600; }
.bar { flex: 1 1 24px; min-width: 16px; height: 2px; background: var(--line); border-radius: 2px; }
.bar.done { background: var(--teal); }
.terminal { margin-left: auto; font-size: .75rem; font-weight: 600; border-radius: 999px; padding: 3px 10px; }
.terminal.complete { background: var(--teal-soft); color: var(--teal); }
.terminal.handoff { background: var(--red-soft); color: var(--red); }

/* status cards */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px;
  margin: 12px 0 20px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
.card .label { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
  font-weight: 600; }
.card .value { font-size: .98rem; font-weight: 600; color: var(--ink); margin-top: 6px; display: flex;
  align-items: center; gap: 8px; flex-wrap: wrap; }
.card .sub { font-size: .78rem; color: var(--muted); margin-top: 4px; }
.pill { font-size: .7rem; font-weight: 600; border-radius: 999px; padding: 2px 8px; }
.pill.ok { background: var(--teal-soft); color: var(--teal); }
.pill.wait { background: var(--amber-soft); color: var(--amber); }
.pill.bad { background: var(--red-soft); color: var(--red); }
.pill.neutral { background: #EEF2F6; color: var(--muted); }

/* chat */
[data-testid="stChatMessage"] { background: var(--surface); border: 1px solid var(--line); border-radius: 14px;
  padding: 14px 16px; margin-bottom: 10px; box-shadow: 0 1px 2px rgba(11, 31, 58, .04); }
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {
  background: #EEF3FA; border-color: #DCE5F1; }
[data-testid="stChatMessage"] p { line-height: 1.6; color: var(--ink); }
[data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"]) [data-testid="stChatMessageAvatarCustom"] {
  background: var(--navy); color: #fff; }
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) [data-testid="stChatMessageAvatarCustom"] {
  background: #D5DEEA; color: var(--navy); }
[data-testid="stChatMessage"] [data-testid="stExpander"] details { border-color: var(--line); border-radius: 10px;
  background: var(--canvas); }
[data-testid="stChatMessage"] [data-testid="stExpander"] summary { font-size: .8rem; color: var(--muted); }
.trace-row { font-size: .8rem; color: var(--muted); margin: 2px 0 8px; }
.tag { display: inline-block; font-size: .72rem; font-family: ui-monospace, Menlo, monospace;
  background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 1px 6px;
  margin: 2px 4px 2px 0; color: var(--ink); }
.tag.warn { border-color: #F5C78A; background: var(--amber-soft); color: var(--amber); }

/* empty state */
.empty { background: var(--surface); border: 1px dashed #CBD5E1; border-radius: 14px; padding: 22px 24px;
  margin-bottom: 14px; }
.empty h3 { font-size: 1rem; margin: 0 0 6px; padding: 0; color: var(--ink); }
.empty ol { margin: 8px 0 0 18px; padding: 0; color: var(--muted); font-size: .88rem; line-height: 1.8; }

/* sidebar */
[data-testid="stSidebar"] .sb-brand { display: flex; align-items: center; gap: 10px; margin: 4px 0 14px; }
[data-testid="stSidebar"] .sb-brand span { font-weight: 700; font-size: 1rem; color: #F8FAFC; }
[data-testid="stSidebar"] .sb-kv { display: flex; justify-content: space-between; gap: 10px; font-size: .8rem;
  padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,.07); }
[data-testid="stSidebar"] .sb-kv span:first-child { color: #94A3B8; }
[data-testid="stSidebar"] .sb-kv span:last-child { color: #E2E8F0; text-align: right; font-weight: 500; }
[data-testid="stSidebar"] .stButton button { justify-content: flex-start; font-size: .84rem; }
[data-testid="stSidebar"] .stButton button > div { justify-content: flex-start; text-align: left; }

[data-testid="stChatMessageAvatarCustom"] [data-testid="stIconMaterial"] { color: inherit !important; }

/* suggested replies */
.sugg-label { font-size: .75rem; color: var(--muted); margin: 4px 0 6px; font-weight: 500; }
[class*="st-key-sugg_"] button { border-radius: 999px; min-height: 0; padding: 4px 12px; background: var(--surface);
  border: 1px solid #BFE3DE; }
[class*="st-key-sugg_"] button p { font-size: .8rem; color: var(--teal); font-weight: 500; }
[class*="st-key-sugg_"] button:hover { background: var(--teal-soft); border-color: var(--teal); }

@media (max-width: 640px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .cards { grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0 14px; }
  .card { padding: 10px 12px; }
  .card:last-child { grid-column: 1 / -1; }
  .card .sub { display: none; }
  .card .value { font-size: .9rem; margin-top: 4px; }
  .stepper { padding: 10px 12px; }
  .step span.lbl { display: none; }
  .step.current span.lbl { display: inline; }
}
</style>
"""

SHIELD = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
          '<path d="M12 2.5 4.5 5.5v6c0 4.6 3.1 8.6 7.5 10 4.4-1.4 7.5-5.4 7.5-10v-6L12 2.5Z" '
          'stroke="#2DD4BF" stroke-width="1.8" stroke-linejoin="round"/>'
          '<path d="m8.5 12 2.5 2.5 4.5-5" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" '
          'stroke-linejoin="round"/></svg>')


def header(session_id: str, model: str | None, today: str, connected: bool) -> str:
    conn = (f'<span class="chip live"><b>{escape(model or "")}</b></span>' if connected
            else '<span class="chip off">Not connected</span>')
    return (f'<div class="app-header"><div class="brand"><div class="brand-mark">{SHIELD}</div>'
            f'<div><h1>Claims Assistant</h1><p>SOP-governed insurance claims support</p></div></div>'
            f'<div class="chips">{conn}<span class="chip">Session <b>{escape(session_id)}</b></span>'
            f'<span class="chip">Demo date <b>{escape(today)}</b></span></div></div>')


def stepper(sop: SessionState) -> str:
    phases = [p for p, _ in STEPS]
    if sop.phase in phases:
        current, stopped = phases.index(sop.phase), False
    elif sop.phase == Phase.HANDOFF and sop.trace and sop.trace[-1].phase_before in phases:
        current, stopped = phases.index(sop.trace[-1].phase_before), True
    else:
        current, stopped = len(phases), False

    parts = []
    for i, (_, label) in enumerate(STEPS):
        if i < current:
            cls, mark = "done", "✓"
        elif i == current:
            cls, mark = ("stopped", "!") if stopped else ("current", str(i + 1))
        else:
            cls, mark = "", str(i + 1)
        parts.append(f'<div class="step {cls}"><div class="dot">{mark}</div><span class="lbl">{label}</span></div>')
        if i < len(STEPS) - 1:
            parts.append(f'<div class="bar {"done" if i < current else ""}"></div>')
    if sop.phase == Phase.COMPLETE:
        parts.append('<span class="terminal complete">Completed</span>')
    elif sop.phase == Phase.HANDOFF:
        parts.append('<span class="terminal handoff">Transferred to a representative</span>')
    return f'<div class="stepper">{"".join(parts)}</div>'


def status_cards(sop: SessionState) -> str:
    # Identity: before verification only field NAMES are shown, never values.
    if sop.verified:
        who = "Representative" if sop.actor_type == "representative" else "Policyholder"
        identity = (f'<div class="value">Verified <span class="pill ok">{who}</span></div>'
                    f'<div class="sub">Account {escape(sop.subject_party_id or "")} · identity locked</div>')
    elif sop.consent_status == "pending":
        identity = ('<div class="value">Awaiting authorization <span class="pill wait">Pending</span></div>'
                    '<div class="sub">Policyholder approval requested</div>')
    elif sop.phase == Phase.HANDOFF:
        identity = '<div class="value">Not verified <span class="pill bad">Stopped</span></div>'
    else:
        got = [FIELD_NAMES[f] for f in sop.provided_pii()]
        sub = ("Received: " + ", ".join(got)) if got else "No details yet"
        identity = (f'<div class="value">Not verified <span class="pill neutral">{len(got)}/3</span></div>'
                    f'<div class="sub">{escape(sub)}</div>')

    # Claim: nothing about any claim until verified.
    if not sop.verified:
        claim = ('<div class="value">Locked <span class="pill neutral">🔒</span></div>'
                 '<div class="sub">Available after verification</div>')
    elif sop.resolved_case_id:
        claim = (f'<div class="value">{escape(sop.resolved_case_id)} <span class="pill ok">In focus</span></div>'
                 '<div class="sub">Answers grounded in this claim</div>')
    else:
        claim = '<div class="value">Selecting claim</div><div class="sub">Matching the caller\'s request</div>'

    email = {
        EmailStatus.NOT_OFFERED: ('Not offered', "neutral", "Offered after the case is handled"),
        EmailStatus.OFFERED: ('Offered', "wait", "Waiting for the caller's choice"),
        EmailStatus.DECLINED: ('Declined', "neutral", "Caller chose not to receive it"),
        EmailStatus.SENT: ('Sent', "ok", "Summary in the mock outbox"),
    }[sop.email_status]
    follow = (f'<div class="value">Email summary <span class="pill {email[1]}">{email[0]}</span></div>'
              f'<div class="sub">{email[2]}</div>')

    return (f'<div class="cards"><div class="card"><div class="label">Identity</div>{identity}</div>'
            f'<div class="card"><div class="label">Claim</div>{claim}</div>'
            f'<div class="card"><div class="label">Follow-up</div>{follow}</div></div>')


def empty_state() -> str:
    return ('<div class="empty"><h3>Connect a model to start</h3>'
            '<ol><li>Open <b>Connection</b> in the sidebar and paste an API key (a free Groq key works).</li>'
            '<li>Pick a <b>test scenario</b>, or type as a caller below.</li>'
            '<li>Open <b>Harness trace</b> under any reply to see what the SOP decided.</li></ol></div>')


def trace_html(phase_before: str, phase_after: str, steps: list[str], prefaces: list[str],
               facts: list[str], notes: list[str]) -> str:
    tags = lambda items, cls="": "".join(f'<span class="tag {cls}">{escape(x)}</span>' for x in items)  # noqa: E731
    rows = [f'<div class="trace-row">Phase <span class="tag">{escape(phase_before)}</span>→'
            f'<span class="tag">{escape(phase_after)}</span></div>',
            f'<div class="trace-row">SOP decided {tags(steps)}</div>']
    if prefaces:
        rows.append(f'<div class="trace-row">Tone {tags(prefaces)}</div>')
    if facts:
        rows.append(f'<div class="trace-row">Facts stated {tags(facts)}</div>')
    if notes:
        rows.append(f'<div class="trace-row">Notes {tags(notes, "warn")}</div>')
    return "".join(rows)


def kv(label: str, value: str) -> str:
    return f'<div class="sb-kv"><span>{escape(label)}</span><span>{escape(value)}</span></div>'


def sidebar_brand() -> str:
    return f'<div class="sb-brand">{SHIELD}<span>Claims Assistant</span></div>'


# ---------------------------------------------------------------- suggested caller replies (testing aid)

# Test identity used by the suggestions, same as the quick scenarios (fixture data, not a real person).
_TEST_DETAILS = {"full_name": "my name is Margaret Chen", "dob": "DOB 1985-03-15", "phone": "phone 650-521-2836",
                 "id_last4": "SSN last four 4472", "email": "email margaret@email.com"}


def suggestions(sop: SessionState, claim_has_documents: bool = False) -> list[str]:
    """What a caller might plausibly say next, chosen from the SOP state. No LLM call, no claim data."""
    if sop.phase in (Phase.COMPLETE, Phase.HANDOFF):
        return []
    if sop.awaiting.value == "handoff_offer":
        return ["Yes, connect me to a person.", "No thanks, let's continue."]

    if sop.phase == Phase.VERIFY_ID:
        if sop.consent_status == "pending":
            return ["She says she approved it.", "Any update?", "Can you just tell me anyway?"]
        if sop.actor_type == "representative" and sop.pending_party_id and not sop.actor_name:
            return ["I'm David Chen."]
        own = sop.identity_claims.get("full_name", "Margaret Chen").lower() == "margaret chen"
        missing = [f for f in ("full_name", "dob", "id_last4", "phone") if f not in sop.identity_claims]
        out = []
        if own and missing:
            needed = max(3 - len(sop.provided_pii()), 1)
            text = ", ".join(_TEST_DETAILS[f] for f in missing[:needed])
            out.append(text[0].upper() + text[1:] + ".")
        out += ["Why do you need my personal details?", "I don't want to give my SSN.",
                "I already told you who I am. Just tell me why my claim was denied.", "What is RL?"]
        return out

    if sop.phase == Phase.RESOLVE_INTENT:
        if sop.awaiting.value == "case_confirm":
            return ["Yes, that's the one.", "No, it's a different claim."]
        if sop.awaiting.value == "case_choice":
            return ["The one from 2026.", "The denied healthcare claim.", "My auto claim."]
        return ["I'm calling about my denied claim.", "What's the status of my auto claim?"]

    if sop.phase == Phase.PROCESS_CASE:
        docs = ["How do I submit the documents?", "What if I can't get the pathology report?",
                "How long does the review take after I submit?"] if claim_has_documents else []
        return docs + ["Which doctor reviewed my claim?", "Can you also check my son's claim?",
                       "What about my other claims?", "No, that's all."]

    # POST_PROCESS
    if sop.awaiting.value == "email":
        return ["Yes, please send it.", "No thanks.", "Maybe later.",
                "Actually, one more question: where do I upload the files?"]
    out = ["No, that's all. Thanks, bye."]
    if sop.email_status.value == "declined":
        out.insert(0, "Actually, please email me the summary.")
    if claim_has_documents:
        out.append("One more question: what file format do you need?")
    return out
