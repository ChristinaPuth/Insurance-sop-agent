# Insurance Claims SOP Agent

A claims support agent that follows a fixed business workflow while still talking naturally:

```
VERIFY_ID  →  RESOLVE_INTENT  →  PROCESS_CASE  →  POST_PROCESS
```

**Deterministic Python owns the workflow** (phase order, identity gates, data access, allowed actions).
**The LLM only reads and writes language**: it extracts signals from what the caller says and phrases the reply
the SOP has already decided on. Strict where the SOP demands it, flexible where reasoning helps.

- Hosted demo: **https://insurance-sop-agentgit-ymsmcdq8a79vh76rvz7jgz.streamlit.app/**
  (bring your own API key: paste it in the sidebar; a free Groq key works)
- Design document: [`docs/Insurance_SOP_Harness_Design.docx`](docs/Insurance_SOP_Harness_Design.docx)
- Test report: [`docs/test-report.md`](docs/test-report.md)
- Numbered rules every test refers to: [`docs/SPEC.md`](docs/SPEC.md)

---

## Using the live demo, step by step

No installation needed. You only need a free API key.

1. **Get a key.** Go to [console.groq.com](https://console.groq.com), sign up, open **API Keys** →
   **Create API Key**, and copy it (it starts with `gsk_`). An OpenAI key (`sk-...`) also works.
2. **Open the demo** (link at the top of this page). On a phone or narrow window, tap **Menu** at the top left
   to open the sidebar.
3. **Connect.** In the sidebar under **Connection**, paste the key into **API key**. Leave **Base URL** and
   **Model** empty; they are filled in automatically. The line under the fields shows the model in use.
4. **Try it.** Click **Reference case** under **Test scenarios**, tap a suggested reply under the chat, or type
   as the caller. Fictional test caller: Margaret Chen, born 1985-03-15, SSN last 4 4472, phone 650-521-2836.
5. **Look inside.** Open **Harness trace** under a reply to see what the model extracted and what the rules
   decided. **Reset conversation** starts over.

### What each test scenario shows

Each test scenario starts a new conversation. The suggested replies under the chat always offer the next step, so most scenarios can be finished by tapping them.

| Scenario | What it tests | How to finish it | Expected |
|---|---|---|---|
| **Reference case** | The full workflow | Tap the suggested replies: "No, that's all." → "Yes, please send it." | Claim CL-2048 explained, email offered, summary in the **Mock outbox** at the bottom |
| **Angry caller** | Empathy without skipping verification | Tap the suggested reply with Margaret's details, confirm the claim ("Yes, that's the one."), then finish as above | No claim details until verified; the held question is answered; same email flow |
| **Off-topic question** | Staying in scope | Tap "What is RL?" two more times, decline the human ("No thanks, let's continue."), then tap Margaret's details | Polite refusals, a human offered on the third; back to normal after that |
| **Wrong identity** | Strict verification | Type the same details with the phone ending in 2831, then 2832 | "Couldn't verify" without naming the wrong field; handoff after 3 tries. **No email: correct by design** |
| **Representative (son)** | Acting for someone else | Tap "She says she approved it.", then finish as in the reference case | Nothing shared before approval; email goes to the **policyholder's** address |
| **Representative, no approval** | Consent that never comes | Tap "Any update?" until the call ends | Nothing shared; handoff. **No email: correct by design** |

### If something goes wrong

| Message | What to do |
|---|---|
| "[Setup problem] ... API key was rejected" | The key is incomplete, deleted or for another service. Paste it again. |
| "[Setup problem] ... model name wasn't found" | Empty the **Model** field, or use the full name: `openai/gpt-oss-120b` (Groq) or `gpt-4.1-mini` (OpenAI). |
| "Our system is busy" | The free key hit its usage limit. Wait a few minutes and resend. |
| The sidebar disappeared | Tap **Menu** at the top left. |

The key stays in your browser tab only. It is never stored by the demo.

## Quick start

You need an API key for any OpenAI-compatible model. A free [Groq](https://console.groq.com) key works.

### Docker

```bash
docker build -t insurance-sop-agent .
docker run -p 8501:8501 -e OPENAI_API_KEY=your-key insurance-sop-agent
```

Open http://localhost:8501. You can also leave `-e OPENAI_API_KEY` out and paste the key into the sidebar.

### Local

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env            # put OPENAI_API_KEY in it (never committed)
.venv/bin/streamlit run app.py  # web UI
.venv/bin/python main.py        # terminal chat (add --trace to see decisions)
```

On Intel Macs, add `--only-binary pyarrow` to the install if the pyarrow build fails.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | API key. The UI also accepts it; it stays in that browser session only |
| `OPENAI_BASE_URL` | OpenAI | Any OpenAI-compatible endpoint. A Groq key (`gsk_…`) selects Groq automatically |
| `MODEL` | `gpt-4.1-mini` (`openai/gpt-oss-120b` on Groq) | Model for both calls |
| `EXTRACT_MODEL` / `RESPONSE_MODEL` | `MODEL` | Override either call separately |
| `DEMO_TODAY` | UI: 2026-02-15 | Date used for appeal deadlines. Unset = real date (CL-2048's deadline has then passed) |
| `DATA_DIR` | `insurance_claims/fixtures` | Fixture directory (read-only) |

In the web UI, anything typed in the sidebar's Connection section wins; empty fields fall back to environment
variables, then `.env`, then the defaults. `.env` is re-read on every request, so editing it needs no restart.

---

## Demo script

The sidebar has **Quick scenarios** that start a fresh conversation with one click. Open **Harness trace**
under any reply to see what the LLM extracted versus what the SOP decided.

| Scenario | What to look for |
|---|---|
| **Reference case** (Margaret) | Verified in one turn; CL-2048 found from the remembered "denied healthcare, January" hint without asking again; denial reason, missing documents and deadline explained; then the email offer |
| **Angry caller** | Acknowledges the frustration, explains why verification protects them, lists the options. No claim detail before verification. The question is held and answered once verified |
| **Off-topic question** | Polite refusal; the third in a row offers a human; a fourth hands off |
| **Wrong identity** | "Couldn't verify" without saying which field was wrong; repeating the same details counts once; three distinct failures hand off |
| **Representative (son)** | David calls for his mother: her details are verified, then her authorization is requested before anything is shared |
| **Representative, no approval** | The policyholder never approves: the agent keeps protecting the data and hands off |

Then continue by hand, e.g. *"How do I submit the documents?"*, *"What if I can't get the pathology report?"*,
*"Which doctor reviewed it?"* (not in the records, so it says so), *"Can you check my son's claim?"*
(identity is locked), *"No, that's all"* → email offer → the **Mock outbox** shows the summary.

---

## How it works

```
caller message
   │
   ▼
① extract (LLM, temperature 0) ──► JSON signals: identity fields, intent, case clues,
   │                                emotion, refusal, yes/no, email decision …  (validated by Pydantic)
   ▼
② remember (Python) ─────────────► stored now, whatever the phase; history saved with PII masked
   ▼
③ decide (Python, pure function) ► verification, case matching, persuasion ladder, phase transitions,
   │                                the steps to perform and the facts that may be stated
   ▼
④ respond (LLM, temperature 0.4) ► phrases ONLY those steps from ONLY those facts
   ▼
⑤ check (Python) ────────────────► fact IDs, dates and amounts must match allowed facts; before
                                    verification no claim term may appear → else fixed fallback text
```

The core is `agent/policy.py` (`decide`, a pure function) and `agent/orchestrator.py` (`handle_turn`, which
copies the state, calls the LLM twice and never mutates its input).

### Freedom per phase

| Phase | LLM decides | Code decides |
|---|---|---|
| VERIFY_ID | Which fields the caller gave, tone, empathy | Whether ≥3 PII match **one** record with no conflicts; when to explain, offer alternatives or a human; nothing about any claim is even loaded |
| RESOLVE_INTENT | What the caller means ("the 2026 one", "why was it denied") | Which of the caller's own claims match; confirm vs. ask vs. proceed |
| PROCESS_CASE | Phrasing and answering the follow-up | Which facts and guideline templates are allowed this turn |
| POST_PROCESS | Phrasing the offer | Email status, recipient (address on file only), content (facts actually said) |

---

## Design decisions

**Information isolation beats prompt instructions.** Claim data is reachable only through `ClaimsRepo`, which
is created after verification (and, for representatives, after authorization) and is bound to that one
policyholder; it has no `party_id` parameter. Before that point the model writing replies has no claim data in
its context, so even a successful jailbreak has nothing to leak. The output check is a tripwire, not the guarantee.

**Verification is deterministic and strict.** At least 3 of {name, DOB, phone, email, SSN/national-ID last 4}
must match the *same* record, no provided field may conflict, and exactly one record may qualify. The policy
number only narrows candidates. Phones match exactly (two numbers in the data differ by one digit); names allow
aliases from the data and reversed order. Repeating the same wrong details counts as one attempt.

**Memory is separate from phase.** Anything useful is stored the moment it is said: a case hint during
verification changes memory, never the phase. After verification the agent uses it instead of asking again.

**No guessing between claims.** Margaret has two January healthcare claims. Recency only orders the list; it
never picks for the caller. A vague request with one candidate is confirmed; a specific one is acted on.

**Follow-ups come from the guideline, not the model's general knowledge.** The extractor classifies the topic;
code fills the matching template from `required_document_guideline.json` (with document-specific guidance);
the model may rephrase but not add facts. An expired appeal deadline overrides "submit within a week".

**Emotion changes the tone, never the gate.** A code-driven ladder per gate: explain why → offer alternative
fields (+ a human) → offer a human → hand off. Cooperating steps it back down. Refusing one field just offers
others. Acknowledgement is not repeated every turn.

**Actor, subject, authorization.** A representative's own name never counts toward the policyholder's PII.
Authorization is requested from the policyholder (mocked from `consent_scenarios.json`); the email goes to the
policyholder's address. Changing identity after verification hands off.

**Every action has fixed fallback text.** If the model is down, rate-limited, or its reply fails the checks,
the SOP still completes with deterministic wording. Handoff messages are always fixed.

**Two LLM calls per turn.** Extraction at temperature 0 sees no claim data; generation sees only this turn's
allowed facts. The isolation is structural, at the cost of roughly double latency.

**JSON, not a database.** The fixtures load once into frozen Pydantic models; session state is separate and
per browser session.

---

## Tests

```bash
.venv/bin/python -m pytest -q
```

99 unit and workflow tests run against a scripted `FakeLLM`, so they need no key. Each references the SPEC
rule it covers (e.g. `# covers V-9`).

### Scenario runner (real model)

`tests/scenarios.yaml` holds 27 end-to-end conversations: the reference case, angry caller, persuasion ladder,
wrong identity, aliases and national ID, ambiguous January, someone else's claim, not-in-records questions,
FAQ follow-ups, expired deadline, email changes, off-topic, prompt injection, representatives with and without
approval. Each turn checks state and forbidden or required phrases, never exact wording.

```bash
.venv/bin/python scripts/run_scenarios.py --pause 20 --report docs/scenario-report.md
.venv/bin/python scripts/run_scenarios.py --only angry_caller representative_consent --verbose
```

It shows live progress, checks the key first, retries rate limits, and labels rate-limited scenarios
separately from real failures. Progress is saved after every scenario: if a run stops (Ctrl+C, network,
quota), run the same command with `--resume`: scenarios that already passed are skipped, and failed, rate-limited
or missing ones run again.

---

## Limitations

- The extraction call necessarily sees the caller's raw message, PII included. Production would need a
  zero-retention endpoint or local entity recognition before the model. Stored history is masked.
- A representative's own identity is self-asserted (the data has no PII for David); safety rests on the
  policyholder's authorization.
- Email sending and policyholder authorization are mocks.
- English only (the guideline data is keyed `en`).
- Severe distress gets a priority offer of a human, not crisis support.
- Sessions live in memory; refreshing the page starts over.

## Layout

```
agent/            harness code
  policy.py         the SOP state machine (pure)
  orchestrator.py   the per-turn loop
  verification.py   identity matching          case_resolver.py   clues → claims
  guidance.py       FAQ templates              consent.py         representative authorization
  facts.py          grounded facts + checks    safety.py          masking + output tripwire
  prompts.py        both system prompts        fallbacks.py       fixed text per action
insurance_claims/fixtures/   provided test data (read-only)
docs/             design document, SPEC.md, test and scenario reports
tests/            pytest suite + scenarios.yaml
scripts/          run_scenarios.py
app.py            Streamlit UI              main.py   terminal chat
```

## Acknowledgements

Designed and built with the help of [Claude](https://claude.com/claude-code) (Anthropic), used as a coding
assistant for design discussion, implementation and tests.
