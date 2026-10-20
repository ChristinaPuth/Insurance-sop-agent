"""Streamlit test UI for the insurance SOP agent. Run: streamlit run app.py"""
from __future__ import annotations

import uuid
from datetime import date

import streamlit as st

from agent.config import load_settings
from agent.data import InsuranceData, load_data
from agent.llm_service import OpenAILLM, default_base_url, default_model
from agent.orchestrator import handle_turn, start_session
from agent.safety import mask_value
from agent.schemas import Phase

SETTINGS = load_settings()
FLOW = [Phase.VERIFY_ID, Phase.RESOLVE_INTENT, Phase.PROCESS_CASE, Phase.POST_PROCESS]

# one-click openers for the demo: (label, first caller message, consent scenario)
QUICK = [
    ("Reference case (Margaret)", "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about "
     "my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.", "default"),
    ("Angry caller", "I already told you who I am. This is ridiculous. Just tell me why my claim was denied.",
     "default"),
    ("Off-topic question", "What is RL?", "default"),
    ("Wrong identity", "I'm Margaret Chen, DOB 1985-03-15, phone 650-521-2830.", "default"),
    ("Representative (son)", "Hi, I'm David Chen, calling for my mother Margaret Chen. Her date of birth is "
     "1985-03-15 and her SSN ends in 4472. It's about her denied healthcare claim from January.", "default"),
    ("Representative, no approval", "Hi, I'm David Chen, calling for my mother Margaret Chen. Her date of birth is "
     "1985-03-15 and her SSN ends in 4472.", "timeout"),
]
CONSENT_LABELS = {"default": "Approves after one check", "timeout": "Never approves (timeout)"}

st.set_page_config(page_title="Claims SOP Agent", page_icon="🛡️", layout="wide")


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

# ---------------------------------------------------------------- sidebar: settings
with st.sidebar:
    st.header("Settings")
    env_key = SETTINGS.api_key
    typed_key = st.text_input("API key", type="password",
                              placeholder="Using OPENAI_API_KEY from environment" if env_key else "sk-...",
                              help="Kept only in this browser session; never logged or stored.")
    base_url = st.text_input("Base URL (optional)", value=SETTINGS.base_url or "",
                             help="Any OpenAI-compatible endpoint.")
    model = st.text_input("Model", value=SETTINGS.response_model)
    default_today = SETTINGS.demo_today or date(2026, 2, 15)
    today = st.date_input("Demo date (DEMO_TODAY)", value=default_today,
                          help="Deadlines are judged against this date.")
    consent_choice = st.selectbox("Policyholder authorization (mock)", list(CONSENT_LABELS),
                                  format_func=CONSENT_LABELS.get, key="consent_choice",
                                  help="How the policyholder responds when a representative calls.")
    if st.session_state.sop.consent_status == "not_required":
        st.session_state.sop.consent_scenario = consent_choice
    if st.button("Reset conversation", use_container_width=True):
        reset()
        st.rerun()

    st.subheader("Quick scenarios")
    st.caption("Starts a fresh conversation and sends the first message.")
    for label, message, scenario in QUICK:
        if st.button(label, use_container_width=True):
            reset(scenario)
            st.session_state.next_consent = scenario
            st.session_state.queued = message
            st.rerun()

api_key = typed_key or env_key
if api_key and not base_url and default_base_url(api_key):
    base_url = default_base_url(api_key)
    st.sidebar.caption(f"Base URL detected from the key: {base_url}")
if api_key and model == SETTINGS.response_model and default_model(api_key) and not SETTINGS.base_url:
    model = default_model(api_key)      # the OpenAI default model does not exist on other providers
    st.sidebar.caption(f"Model set for this provider: {model}")
llm_key = (api_key, base_url, model)
if api_key and st.session_state.get("llm_key") != llm_key:
    try:
        st.session_state.llm = OpenAILLM(api_key, model, model, base_url or None)   # per session (X-6)
        st.session_state.llm_key = llm_key
    except Exception:  # noqa: BLE001 - never echo the key or SDK internals (X-5)
        st.session_state.llm = None
        st.sidebar.error("Could not create the API client. Check the key and base URL.")
llm = st.session_state.get("llm") if api_key else None

sop = st.session_state.sop

# ---------------------------------------------------------------- sidebar: harness state
with st.sidebar:
    st.divider()
    st.header("Harness state")
    cols = st.columns(4)
    if sop.phase in FLOW:
        current = FLOW.index(sop.phase)
    elif sop.phase == Phase.HANDOFF and sop.trace:      # show where the handoff happened, not "all done"
        current = FLOW.index(sop.trace[-1].phase_before)
    else:
        current = len(FLOW)
    for i, (col, ph) in enumerate(zip(cols, FLOW)):
        here = "🛑" if sop.phase == Phase.HANDOFF else "🟦"
        mark = "✅" if i < current else (here if i == current else "⬜")
        col.caption(f"{mark}\n{ph.value.replace('_', ' ')}")
    if sop.phase in (Phase.COMPLETE, Phase.HANDOFF):
        st.info(f"Phase: **{sop.phase.value}**")

    st.markdown(f"**Verified:** {'✅ ' + sop.subject_party_id if sop.verified else '❌'}")
    if sop.actor_type == "representative":
        who = (sop.actor_name or "name not given").split()[0]
        st.markdown(f"**Caller:** representative ({who}) · authorization `{sop.consent_status}`"
                    f" · mock: {CONSENT_LABELS.get(sop.consent_scenario, sop.consent_scenario)}")
    ids = {f: mask_value(f, v) for f, v in sop.identity_claims.items()}
    st.markdown("**Identity provided:** " + (", ".join(f"`{k}={v}`" for k, v in ids.items()) or "—"))
    st.markdown(f"**Remembered intent:** {sop.intent.value if sop.intent else '—'}")
    hint = sop.case_query.model_dump(exclude_none=True)
    st.markdown(f"**Remembered case hint:** {hint or '—'}")
    if sop.pending_questions:
        st.markdown(f"**Questions held until verified:** {len(sop.pending_questions)}")
    st.markdown(f"**Case:** {sop.resolved_case_id or '—'}")
    st.markdown(f"**Email:** {sop.email_status.value}")
    st.caption(f"verify failures {sop.verify_failures}/3 · off-topic streak {sop.off_topic_streak} · "
               f"awaiting {sop.awaiting.value} · session {sop.session_id}")

# ---------------------------------------------------------------- main: chat
st.title("Insurance Claims Support — SOP Agent")
if not api_key:
    st.warning("Enter an API key in the sidebar (or set OPENAI_API_KEY) to start chatting.")

traces = {t.turn: t for t in sop.trace}
for role, text, turn in st.session_state.display:
    with st.chat_message("assistant" if role == "agent" else "user"):
        st.write(text)
        if role == "agent" and turn in traces:
            t = traces[turn]
            with st.expander("Harness trace", expanded=False):
                st.markdown(f"`{t.phase_before.value}` → `{t.phase_after.value}`")
                st.markdown("**LLM extracted (masked):**")
                st.json(t.extraction, expanded=False)
                st.markdown("**SOP decided:** " + " → ".join(t.steps))
                if t.prefaces:
                    st.markdown("**Prefaces:** " + ", ".join(t.prefaces))
                if t.facts_recorded:
                    st.markdown("**Facts recorded:** " + ", ".join(t.facts_recorded))
                for n in t.notes:
                    st.caption("⚠️ " + n)

if sop.outbox:
    with st.expander("📧 Mock outbox — not actually sent", expanded=True):
        for mail in sop.outbox:
            st.markdown(f"**To:** {mail.to_masked}  \n**Subject:** {mail.subject}")
            st.code(mail.body, language=None)

if sop.handoff:
    with st.expander("🧑‍💼 Handoff — Agent view (internal)", expanded=True):
        st.caption("Visible to the receiving representative only. Contains no PII values.")
        st.json(sop.handoff.internal_summary)

ended = sop.phase in (Phase.COMPLETE, Phase.HANDOFF)
typed = st.chat_input("Conversation ended — reset to start again" if ended else "Type your message…",
                      disabled=not api_key or ended)
prompt = typed or (st.session_state.pop("queued", None) if api_key else None)
if prompt:
    st.session_state.display.append(("user", prompt, None))
    with st.spinner("Thinking…"):
        new_state, reply = handle_turn(sop, prompt, llm, get_data(), today, SETTINGS.thresholds)
    st.session_state.sop = new_state
    st.session_state.display.append(("agent", reply, new_state.turn))
    st.rerun()
