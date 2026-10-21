"""Streamlit test UI for the insurance SOP agent. Run: streamlit run app.py

Presentation only: every decision is made by agent.orchestrator / agent.policy.
"""
from __future__ import annotations

import uuid
from datetime import date

import streamlit as st

import ui
from agent.config import load_settings
from agent.claims import repo_for
from agent.data import InsuranceData, load_data
from agent.llm_service import OpenAILLM, resolve_connection
from agent.orchestrator import handle_turn, start_session
from agent.safety import mask_value
from agent.schemas import Phase

SETTINGS = load_settings()        # Streamlit re-runs this script on every interaction, so .env edits apply at once

# one-click openers for the demo: (label, icon, first caller message, consent scenario)
QUICK = [
    ("Reference case", ":material/verified_user:", "I'm the policyholder. My name is Margaret Chen, policy POL-9921. "
     "I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.", "default"),
    ("Angry caller", ":material/sentiment_dissatisfied:",
     "I already told you who I am. This is ridiculous. Just tell me why my claim was denied.", "default"),
    ("Off-topic question", ":material/block:", "What is RL?", "default"),
    ("Wrong identity", ":material/gpp_bad:", "I'm Margaret Chen, DOB 1985-03-15, phone 650-521-2830.", "default"),
    ("Representative (son)", ":material/family_restroom:", "Hi, I'm David Chen, calling for my mother Margaret "
     "Chen. Her date of birth is 1985-03-15 and her SSN ends in 4472. It's about her denied healthcare claim from "
     "January.", "default"),
    ("Representative, no approval", ":material/hourglass_disabled:", "Hi, I'm David Chen, calling for my mother "
     "Margaret Chen. Her date of birth is 1985-03-15 and her SSN ends in 4472.", "timeout"),
]
CONSENT_LABELS = {"default": "Approves after one check", "timeout": "Never approves (timeout)"}
AVATARS = {"agent": ":material/support_agent:", "user": ":material/person:"}

st.set_page_config(page_title="Claims Assistant", page_icon=":material/shield:", layout="wide",
                   initial_sidebar_state="auto")   # open on desktop, closed on phones (Menu button reopens it)
st.markdown(ui.CSS, unsafe_allow_html=True)


@st.cache_resource
def get_data() -> InsuranceData:
    """Read-only fixtures are safe to share across sessions (X-6). LLM clients are not."""
    return load_data(SETTINGS.data_dir)


def reset(consent_scenario: str | None = None) -> None:
    sid = "SES-" + uuid.uuid4().hex[:4].upper()
    st.session_state.sop = start_session(sid)
    st.session_state.sop.consent_scenario = consent_scenario or st.session_state.get("consent_choice", "default")
    st.session_state.display = [("agent", st.session_state.sop.history[0].text, None)]


if "sop" not in st.session_state:
    reset()
if "next_consent" in st.session_state:          # widget values can only be set before the widget is drawn
    st.session_state.consent_choice = st.session_state.pop("next_consent")

# ---------------------------------------------------------------- sidebar: connection + test tools
env_key = SETTINGS.api_key
with st.sidebar:
    st.markdown(ui.sidebar_brand(), unsafe_allow_html=True)

    with st.expander("Connection", icon=":material/key:", expanded=not env_key):
        st.caption("Leave a field empty to use the value from .env. Anything typed here takes priority.")
        typed_key = st.text_input("API key", type="password",
                                  placeholder="Using the key from .env" if env_key else "Paste key",
                                  help="Kept only in this browser session; never logged or stored.")
        typed_base = st.text_input("Base URL (optional)",
                                   placeholder=SETTINGS.base_url or "Auto: OpenAI, or Groq for gsk_ keys",
                                   help="Any OpenAI-compatible endpoint.")
        typed_model = st.text_input("Model",
                                    placeholder=(SETTINGS.response_model if SETTINGS.model_configured
                                                 else "Auto: gpt-4.1-mini, or gpt-oss-120b on Groq"))
        conn_note = st.empty()

    with st.expander("Test scenarios", icon=":material/science:", expanded=True):
        st.caption("Each starts a fresh conversation and sends the first caller message.")
        for label, icon, message, scenario in QUICK:
            if st.button(label, icon=icon, use_container_width=True):
                reset(scenario)
                st.session_state.next_consent = scenario
                st.session_state.queued = message
                st.rerun()
        st.divider()
        # fixed, meaningful dates instead of a calendar (the picker follows the browser's language)
        date_options = {"Feb 15, 2026 · before CL-2048's appeal deadline": date(2026, 2, 15),
                        "Oct 19, 2026 · after the appeal deadline": date(2026, 10, 19),
                        f"Today ({date.today():%b %d, %Y})": date.today()}
        if SETTINGS.demo_today and SETTINGS.demo_today not in date_options.values():
            date_options = {f"{SETTINGS.demo_today:%b %d, %Y} · from DEMO_TODAY": SETTINGS.demo_today, **date_options}
        default_label = next(k for k, v in date_options.items() if v == (SETTINGS.demo_today or date(2026, 2, 15)))
        custom = "Custom date…"
        labels = [*date_options, custom]
        today_label = st.selectbox("Demo date", labels, index=labels.index(default_label),
                                   help="Appeal deadlines are judged against this date.")
        if today_label == custom:           # only one date ever applies: the calendar replaces the preset
            today = st.date_input("Pick a date", value=date(2026, 2, 15), label_visibility="collapsed")
        else:
            today = date_options[today_label]
        consent_choice = st.selectbox("Policyholder authorization (mock)", list(CONSENT_LABELS),
                                      format_func=CONSENT_LABELS.get, key="consent_choice",
                                      help="How the policyholder responds when a representative calls.")
        if st.session_state.sop.consent_status == "not_required":
            st.session_state.sop.consent_scenario = consent_choice
        if st.button("Reset conversation", icon=":material/restart_alt:", use_container_width=True, type="primary"):
            reset()
            st.rerun()

# ---------------------------------------------------------------- per-session LLM client
conn = resolve_connection(SETTINGS, typed_key, typed_base, typed_model)   # site first, then .env (K-1..K-3)
api_key, base_url, model = conn.api_key, conn.base_url, conn.model
notes = []
if api_key:
    notes.append(f"Key: {conn.key_source}  \nModel: **{model}** ({conn.model_source})  \n"
                 f"Endpoint: {base_url or 'api.openai.com'} ({conn.base_source})")
llm_key = (api_key, base_url, model)
if api_key and st.session_state.get("llm_key") != llm_key:
    try:
        st.session_state.llm = OpenAILLM(api_key, model, model, base_url or None)   # per session (X-6)
        st.session_state.llm_key = llm_key
    except Exception:  # noqa: BLE001 - never echo the key or SDK internals (X-5)
        st.session_state.llm = None
        notes.append("Could not create the API client. Check the key and base URL.")
llm = st.session_state.get("llm") if api_key else None
if notes:
    conn_note.caption("  \n".join(notes))

sop = st.session_state.sop

# ---------------------------------------------------------------- sidebar: session details
with st.sidebar:
    with st.expander("Session details", icon=":material/monitoring:", expanded=False):
        rows = [("Phase", sop.phase.value.replace("_", " ").title()),
                ("Caller", "Representative" if sop.actor_type == "representative" else "Policyholder")]
        if sop.actor_type == "representative":
            rows.append(("Authorization", sop.consent_status.replace("_", " ")))
        if sop.verified:   # masked values only after verification; field names only before
            rows += [(ui.FIELD_NAMES[f], mask_value(f, v)) for f, v in sop.identity_claims.items()]
        else:
            rows.append(("Details received", ", ".join(ui.FIELD_NAMES[f] for f in sop.provided_pii()) or "—"))
        hint = sop.case_query.model_dump(exclude_none=True)
        rows += [("Remembered intent", sop.intent.value.replace("_", " ") if sop.intent else "—"),
                 ("Remembered clues", ", ".join(f"{k}={v}" for k, v in hint.items()) or "—"),
                 ("Held questions", str(len(sop.pending_questions))),
                 ("Verify failures", f"{sop.verify_failures} / 3"),
                 ("Off-topic streak", str(sop.off_topic_streak)),
                 ("Persuasion level", f"L{sop.escalation_level}"),
                 ("Awaiting", sop.awaiting.value.replace("_", " "))]
        st.markdown("".join(ui.kv(k, v) for k, v in rows), unsafe_allow_html=True)

# ---------------------------------------------------------------- main
connected = bool(api_key and llm)
st.markdown(ui.header(sop.session_id, model if connected else None, today.isoformat(), connected),
            unsafe_allow_html=True)
st.markdown(ui.stepper(sop), unsafe_allow_html=True)
st.markdown(ui.status_cards(sop), unsafe_allow_html=True)
if not api_key:
    st.markdown(ui.empty_state(), unsafe_allow_html=True)

traces = {t.turn: t for t in sop.trace}
for role, text, turn in st.session_state.display:
    with st.chat_message("assistant" if role == "agent" else "user", avatar=AVATARS[role]):
        st.markdown(text)
        if role == "agent" and turn in traces:
            t = traces[turn]
            label = "Harness trace" + (" · note" if t.notes else "")
            with st.expander(label, icon=":material/account_tree:", expanded=False):
                st.markdown(ui.trace_html(t.phase_before.value, t.phase_after.value, t.steps, t.prefaces,
                                          t.facts_recorded, t.notes), unsafe_allow_html=True)
                st.caption("Signals extracted by the LLM (identity values masked)")
                st.json(t.extraction, expanded=False)

if sop.outbox:
    with st.container(border=True):
        st.markdown("**:material/mail: Mock outbox** · not actually sent")
        for mail in sop.outbox:
            st.caption(f"To {mail.to_masked} · {mail.subject}")
            st.code(mail.body, language=None)

if sop.handoff:
    with st.container(border=True):
        st.markdown(f"**:material/support_agent: Handoff {sop.handoff.reference}** · representative view (internal)")
        st.caption("Shared only with the receiving representative. Contains no identity values.")
        st.json(sop.handoff.internal_summary, expanded=False)

ended = sop.phase in (Phase.COMPLETE, Phase.HANDOFF)

# suggested caller replies: a testing aid chosen from the SOP state (no extra LLM calls)
if api_key and not ended:
    repo = repo_for(sop, get_data())          # None before verification: no claim data is consulted
    claim = repo.get_claim(sop.resolved_case_id) if repo and sop.resolved_case_id else None
    options = ui.suggestions(sop, claim_has_documents=bool(claim and claim.documents_needed))
    if options:
        st.markdown('<div class="sugg-label">Try a caller reply</div>', unsafe_allow_html=True)
        with st.container(horizontal=True, gap="small"):
            for i, text in enumerate(options):
                if st.button(text, key=f"sugg_{sop.turn}_{i}"):
                    st.session_state.queued = text
                    st.rerun()

placeholder =("Conversation ended — reset to start again" if ended
               else "Message the claims assistant…" if api_key else "Connect a model in the sidebar to start")
typed = st.chat_input(placeholder, disabled=not api_key or ended)
prompt = typed or (st.session_state.pop("queued", None) if api_key else None)
if prompt:
    st.session_state.display.append(("user", prompt, None))
    with st.spinner("Working on it…"):
        new_state, reply = handle_turn(sop, prompt, llm, get_data(), today, SETTINGS.thresholds)
    st.session_state.sop = new_state
    st.session_state.display.append(("agent", reply, new_state.turn))
    st.rerun()
