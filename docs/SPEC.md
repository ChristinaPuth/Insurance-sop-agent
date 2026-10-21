# Insurance SOP Agent: Specification

This file describes how the system works today. It is the reference for both the code and the tests. Every rule has an ID, and each test names the rules it covers (for example `# covers V-3`).

For the reasoning behind these rules, see the design document: `docs/Insurance_SOP_Harness_Design.docx`.

---

## 0. Principles

| ID | Rule |
|---|---|
| G-1 | Python decides phases, permissions, counters and transitions. The model only returns **signals** (extraction) and **wording** (the reply). |
| G-2 | Keep data out of the model's reach instead of relying on prompt instructions: the reply call sees only the facts the current phase allows. |
| G-3 | Every action has fixed fallback text, so the process still completes when the model is unavailable, rate-limited, or its reply fails a check. |
| G-4 | `policy.decide(state, ext, data, today) -> list[Step]` is a **pure function**. `data` is read-only, in-memory data passed in as an argument (plus the `ClaimsRepo` bound under D-2). It never calls the model, does no I/O, never changes its inputs, and returns the same output for the same input. `handle_turn(state, msg, llm, data, today) -> (next_state, reply)` **orchestrates** the turn. It calls the model, so it has side effects, but it deep-copies the state first and only changes the copy. `today` is passed in from the entry point. |
| G-5 | Conversations are in English only. |

---

## 1. Data

| ID | Rule |
|---|---|
| D-1 | `insurance_claims/fixtures/*.json` (path set by `DATA_DIR`) is loaded at startup into read-only Pydantic models (`frozen=True`, tuples for lists, read-only mappings for dicts). No database. The provided files are never edited. |
| D-2 | `ClaimsRepo(data, authorized_party_id)` is created only after verification (and authorization, for representatives). None of its methods take a `party_id`. `get_claim` returns `None` for a claim that belongs to someone else. |
| D-3 | Demo date: the `DEMO_TODAY` environment variable if set, otherwise the real date. It is read only at the entry point and passed in as a parameter. The UI also offers preset dates (U-6). |
| D-4 | Document names: a claim's document matches a guideline key when every word of the document name appears in the key. Otherwise the default guidance is used. |
| D-5 | Any amount that is explained must come with its definition from `claim_schema.json`. The first presentation of a claim (PRESENT_CASE) may mention only `net_pay`. The other amounts are easy to mistake for a payout, so they are given only on follow-up. |

---

## 2. State machine

```python
class Phase(str, Enum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    COMPLETE = "COMPLETE"    # end state
    HANDOFF = "HANDOFF"      # end state
```

| ID | From | When | To |
|---|---|---|---|
| S-1 | VERIFY_ID | Verification passes (V-1); a representative also needs consent=approved | RESOLVE_INTENT |
| S-2 | VERIFY_ID | `verify_failures == 3`, or authorization times out | HANDOFF |
| S-3 | RESOLVE_INTENT | The claim is settled (C rules) | PROCESS_CASE |
| S-4 | RESOLVE_INTENT | No claims on file, or the caller has nothing to handle. No applicable gate may be skipped. | POST_PROCESS |
| S-5 | PROCESS_CASE | `switch_case` | RESOLVE_INTENT |
| S-6 | PROCESS_CASE | `is_done`, or "no" to "anything else?" | POST_PROCESS |
| S-7 | POST_PROCESS | Follow-up on the same claim: stay, set `pending_followup=True`, then re-offer the email per P-8. A real question is answered before any "unclear" email handling (P-3). | POST_PROCESS |
| S-8 | POST_PROCESS | Question about a different claim | RESOLVE_INTENT |
| S-9 | POST_PROCESS | (`email_status` is DECLINED or SENT, **or** no email is offered because `discussed_facts` is empty and the status is still NOT_OFFERED) and the caller has answered "anything else?" | COMPLETE |
| S-10 | any | `wants_human`, accepting an offered human, a fourth off-topic message after the offer (O-3), ladder level L4, a second insult, or an identity change after verification (A-4) | HANDOFF |
| S-11 | all | Not allowed: leaving VERIFY_ID without verification (VERIFY_ID only goes to RESOLVE_INTENT or HANDOFF); returning to VERIFY_ID once verified; RESOLVE_INTENT going to POST_PROCESS except as in S-4; leaving an end state. | n/a |
| S-12 | all | A turn can move through up to 3 transitions and still produces one reply. Signals that answer the agent's last question (yes/no, done, email choice) are read only in the phase where the turn started. | n/a |

---

## 3. One turn

```
copy state → extract (model, temperature 0) → keyword safety nets → merge memory
→ policy.decide loop (≤3) → build context → respond (model, temperature 0.4)
→ fact checks (T-3, T-6) → output check → record facts
```

| ID | Rule |
|---|---|
| T-1 | If the extraction fails validation, retry once with the error included. If it fails again, reply with `CLARIFY` and leave the state unchanged. An API 400 (JSON-mode validation error) is also retried once. |
| T-2 | If the reply call fails, use the action's fallback text. |
| T-3 | The reply comes back as `AgentReply{text, used_fact_ids}`. A fact is added to `discussed_facts` only when (1) its id is in this turn's `must_state ∪ may_state` (any other id is dropped), and (2) its keywords (claim id, document names, dates, amounts) appear in `text`. The keyword check shows a fact was mentioned, not that it was stated correctly. Meaning is covered by the real-model scenarios. |
| T-4 | Any `must_state` fact the reply left out is appended using its fallback sentence. |
| T-5 | Each turn writes a `trace` entry: masked extraction, actions, prefaces, phase change, facts recorded, and notes (fallbacks, blocked replies, safety nets that fired). |
| T-6 | Date and amount check: every amount and date in the reply must equal a value from this turn's allowed facts or from this turn's action parameters (code-built text such as candidate claim summaries). Several date formats are recognized. On a mismatch, the reply is dropped, the fallback text is used, and the trace records why. |
| T-7 | Sentences appended under T-4 are written by code, so their facts are recorded without the T-3 check. |
| T-8 | The reply call receives `CALLER_LATEST_MESSAGE` (this turn's message, masked) so it can answer the question that was actually asked. |
| T-9 | API errors: 401/403/404 are setup problems and get a fixed "[Setup problem]" message; 429 is a rate limit and gets "our system is busy, please resend"; anything else follows T-1 or T-2. Error text holds only the exception type and status code, never request headers or the key. The SDK retries 429s after the wait the server asks for. |

---

## 4. Extraction result

```json
{
  "identity": {"full_name": null, "dob": null, "phone": null, "email": null,
               "id_last4": null, "id_type_stated": null},
  "policy_number": null,
  "caller_role": "unknown | policyholder | representative",
  "actor_name": null,
  "intent": "denial_question | status_inquiry | document_submission | next_steps | general_claim_question | null",
  "case_hint": {"case_id": null, "case_type": null, "status": null, "month": null, "year": null, "amount": null},
  "followup_topic": "submission_timing | processing_time | submission_method | file_format | receipt_confirmation | doc_alternatives | none",
  "emotion": {"type": "neutral | frustration | anger | anxiety | confusion", "intensity": 0, "abusive": false, "distress": false},
  "refusal": {"target": "none | field | verification | consent | email", "field": null},
  "off_topic": "none | out_of_role | unrelated | smalltalk | non_english",
  "wants_human": false, "is_done": false, "switch_case": false, "about_other_person": false,
  "asks_to_skip": false, "asks_question": false, "answer": "none | yes | no",
  "email_decision": "none | yes | no | unclear",
  "corrections": []
}
```

| ID | Rule |
|---|---|
| E-1 | The model copies values exactly as the caller typed them. `normalize.py` normalizes them (dates to ISO, phones to E.164, names to word sets). |
| E-2 | A new value replaces the old one and a `Correction` is logged. Identity fields stop updating once verification passes. |
| E-3 | Intent and claim clues are stored as soon as they appear, in any phase, without changing the phase. |
| E-4 | A claim question asked before verification goes into `pending_questions` and is answered once the caller is verified and the claim is found. |
| E-5 | `answer` only means the caller's reply to the agent's last yes/no question; how it is read depends on `state.awaiting`. `asks_question` is only for questions about the caller's own claim or the claims process. General-knowledge or off-topic questions do not count. |
| E-6 | When a representative calls, `identity.*` holds the policyholder's details. `actor_name` is the caller. |
| E-7 | Keyword safety nets (in the orchestrator, used when the model misses a signal): "my son/wife/... + claim/policy" sets `about_other_person` (A-5); "I don't want to give my SSN/phone/..." sets `refusal = field` (M-6, VERIFY_ID only). When the model does report a field refusal but names the field its own way ("ssn", "date_of_birth") or leaves it empty, the name is mapped to ours or taken from the keyword rule. If the model reads a refusal of one named field as refusing verification altogether, the keyword rule turns it back into a field refusal. Each use is logged in the trace. |

---

## 5. Identity verification

| ID | Rule |
|---|---|
| V-1 | Verification passes when at least 3 identity fields match **the same** record, **and** none of the provided fields conflict with it, **and** exactly one record meets both conditions. Identity fields = {full_name, dob, phone, email, id_last4}. |
| V-2 | `policy_number` only narrows the candidates (when it matches a record). It is not one of the identity fields. |
| V-3 | Name: case and punctuation ignored, `name_aliases` checked, word order ignored. |
| V-4 | Date of birth and ID last 4: exact comparison after normalization. |
| V-5 | Phone: exact E.164 comparison, `phone_aliases` checked. **No fuzzy matching.** |
| V-6 | Email: case-insensitive, `email_aliases` checked. |
| V-7 | If the ID type the caller names doesn't match the record's `id_type`, that field counts as neither a match nor a conflict. |
| V-8 | When asking for an ID, use neutral wording ("SSN or national ID"). |
| V-9 | Only **new attempts** count. A fingerprint is taken of the provided fields (name + normalized value + stated ID type). Verification runs again only when at least 3 fields are present and the fingerprint differs from the last attempt; a failure then adds 1 to `verify_failures`. Repeating the same wrong details counts once. Fewer than 3 fields never counts. 3 failures go to HANDOFF. |
| V-10 | A failure message never says which field was wrong and never suggests that the account exists. |
| V-11 | Aliases come only from the data files. |

---

## 6. Representatives and consent

| ID | Rule |
|---|---|
| A-1 | The state keeps `actor_type`, `actor_name`, `subject_party_id`, `pending_party_id` and `consent_status` separate. |
| A-2 | A representative gets through when `actor_name` matches that policyholder's entry in `representatives.json`, 3 of the policyholder's identity fields pass V-1, and consent=approved. The caller's own name never counts toward the policyholder's fields. |
| A-3 | The consent sequence comes from `consent_scenarios.json`; the UI picks which one. Each check moves one step along the sequence. If the last step is still pending, it is a timeout and goes to HANDOFF. |
| A-4 | Becoming a representative before verification: switch flows and keep the policyholder details already collected. After verification: HANDOFF. |
| A-5 | After verification `identity_locked=True`. A question about someone else's claim (`about_other_person`) gets `OTHER_PERSON_LOCKED`: the agent explains it can only access the verified policyholder's claims, and nothing is switched or looked up. |
| A-6 | In a representative call, the email goes to the policyholder's address on file, and the caller is told so. |
| A-7 | The first consent check happens in the turn the request is sent, then one per turn. With no caller name, ask for it first (`ASK_ACTOR_NAME`). A name not on the representative list goes to HANDOFF. Before approval `subject_party_id` stays empty and only `pending_party_id` is set, so D-2 data access is not available yet. |

---

## 7. Finding the claim

| ID | Rule |
|---|---|
| C-1 | With a claim id, look it up exactly in `ClaimsRepo`. If it isn't the caller's, say "I can't find that claim on your account" and nothing about who owns it. |
| C-2 | A request is specific when it gives at least 2 of: claim type, status, time, amount; or a claim id. With `intent = denial_question` and no status, treat the status as denied (this counts as one clue). |
| C-3 | Specific and unique: go ahead, and name the claim id and date in the reply. |
| C-4 | Vague but unique: `CONFIRM_CASE` with a summary of the candidate. |
| C-5 | Several candidates: `DISAMBIGUATE_CASE`. **Recency only orders the list; it never chooses for the caller.** |
| C-6 | No match: `NO_MATCHING_CASE` and list the caller's claims. No claims at all: `NO_CASES_ON_FILE`, then POST_PROCESS. |
| C-7 | Relative dates ("last January") are read against the demo date. If that doesn't settle it, ask. |
| C-8 | Before verification, never confirm whether a claim id exists. `ACK_HINT` only repeats the clues the caller gave. |

---

## 8. Handling the claim and follow-ups

| ID | Rule |
|---|---|
| F-1 | The extractor sets `followup_topic`. Code takes the matching template and fills in `{case_id}`, `{documents}` and `{average_processing_time_after_submission}`. |
| F-2 | Questions about file format or how to submit also get the guidance for each document (D-4), the claim type's guidance, and the default guidance. |
| F-3 | The model may reword facts but not add or remove any. |
| F-4 | No matching topic: use `claim_followup_fallback` and offer a representative. |
| F-5 | Before the deadline: give both "submit within a week" and `appeal_deadline`; the deadline is the hard limit. |
| F-6 | After the deadline (`today > appeal_deadline`): **this overrides F-5**. Don't use the submission-timing template or give any submission advice. Say the deadline has passed, promise neither an appeal nor an extension, and suggest a representative. |
| F-7 | Don't make up anything that isn't in the records (coverage questions included). Answer the question that was asked without repeating facts already given. If the facts don't answer it, say it can't be confirmed from the records and offer a representative. |
| F-8 | Asked why a claim that wasn't denied was denied: correct the status. |
| F-9 | If the caller can't get a document, give the alternatives from `document_alternative_guidance`, and point to a human review if none work. |
| F-10 | The extractor's topic names differ from the guideline's `topic` keys (`processing_time` → `processing_time_after_submission`, `file_format` → `file_format_requirements`). `guidance.TOPIC_KEYS` maps them, and a test checks that every topic has an entry. |

---

## 9. Staying in scope

| ID | Rule |
|---|---|
| O-1 | `unrelated` and `out_of_role` add to `off_topic_streak`; `smalltalk` and `non_english` don't. A message judged off-topic does not become relevant just because it is phrased as a question. |
| O-2 | If the same message also carries something useful (identity details, intent, claim clues, an answer to the last question), set the off-topic part aside, handle the rest, and don't count it. |
| O-3 | At streak 3: `OFFER_HANDOFF` (offer only). Accepting goes to HANDOFF; returning to the claim resets the streak; streak 4 after the offer goes to HANDOFF. |
| O-4 | Prompt injection is treated as `unrelated` and doesn't change the phase. |
| O-5 | General insurance terms may get a short general explanation; fields defined in the schema use the schema's definition. |
| O-6 | `out_of_role`: say another team handles it and a representative can redirect them. `non_english`: add the `ENGLISH_ONLY` preface and don't count it. |

---

## 10. Emotion and persuasion

| ID | Rule |
|---|---|
| M-1 | Emotion and refusal are separate signals, both from the same extraction call. |
| M-2 | Persuasion ladder (`escalation_level`): L1 acknowledge and explain why (EXPLAIN_GATE) → L2 acknowledge, offer other fields, mention a human (OFFER_ALT_FIELDS) → L3 offer a human (OFFER_HANDOFF) → L4 hand off (HANDOFF). |
| M-3 | Move up when the caller refuses a gate, or shows frustration or anger at intensity 2 or more during a gate. |
| M-4 | Move down one level when the caller gives a new valid field; reset `no_progress_turns`. |
| M-5 | When to stop persuading: third refusal of the same gate → L3, fourth → L4; anger at 3 for 2 turns in a row → L3; first insult is de-escalated, second → HANDOFF; `no_progress_turns == 4` → L3; asking for a person → HANDOFF at once; severe distress → L3 (offer a human first). |
| M-6 | Refusing one field gets `OFFER_ALT_FIELDS` and does not add to `gate_refusals`, even if the model also flagged a wish to skip verification. |
| M-7 | Use `ACK_EMOTION` only when a feeling appears or gets stronger. |
| M-8 | Never: trade partial information for cooperation, promise an outcome, blame anyone, or use guilt. |
| M-9 | The reasons for each gate come from code (`fallbacks.GATE_REASON`, `consent.CONSENT_REASON`); the model only rewords them. |
| M-10 | Thresholds live in `config.py`. |
| M-11 | If the caller declines the human offered at L3 (and doesn't refuse verification again in that turn), go back to L2 and keep verifying. The orchestrator keeps `anger_streak` and `abuse_count` up to date each turn; the rules that use them live in the policy. |

---

## 11. Wrap-up and the email summary

| ID | Rule |
|---|---|
| P-1 | `EmailStatus`: NOT_OFFERED → OFFERED → DECLINED or SENT. DECLINED can still change to yes before COMPLETE. SENT is final: never resent or recalled. |
| P-2 | Offer the email only when `discussed_facts` is not empty. Otherwise skip it, leave the status at NOT_OFFERED, and go straight to `ASK_ANYTHING_ELSE` (which satisfies S-9). Don't offer it during a handoff. |
| P-3 | `unclear` gets `RECONFIRM_EMAIL` once. A second unclear answer counts as no, never as yes. |
| P-4 | Send only to the address on file, confirmed in masked form (`m*****@email.com`). An address given in the conversation is not accepted. |
| P-5 | The email is rendered from a fixed template, **section by section**, using only `discussed_facts`. A section with no facts is left out. No identity values, emotions or internal notes. |
| P-6 | An `EmailSender` interface with only `MockEmailSender` implemented. The UI labels it "Mock outbox · not actually sent". |
| P-7 | After SENT, the phase stays POST_PROCESS. Follow-ups on the same claim are answered with a note that this part isn't in the email already sent. Nothing is resent. |
| P-8 | After a follow-up, whether to offer the email again: OFFERED → offer once more; DECLINED → don't ask again (the caller can still ask for it); SENT → don't ask. |

---

## 12. Handoff

| ID | Rule |
|---|---|
| H-1 | `wants_human` goes to HANDOFF at once. If the caller isn't verified, add a note that the representative will still check their identity. |
| H-2 | `HandoffRecord` = `internal_summary` + `user_message` (with a reference number, H-xxxx). |
| H-3 | The internal summary holds the reason, caller type, consent status, emotion, what the caller said they wanted and their clues, which identity fields were given (not the values), and the failure count. Account, claim and discussed facts are included only after verification. |
| H-4 | A turn that includes HANDOFF does not call the reply model; it uses fixed text. |

---

## 13. Privacy and security

| ID | Rule |
|---|---|
| X-1 | `history` is stored masked right after extraction: `[NAME] [DOB] [ID_LAST4] [PHONE] [EMAIL]`. |
| X-2 | The reply call gets no personal data before verification, and only a first name afterwards (`display_name`; the representative's own name in a representative call). |
| X-3 | Identity details are always masked in the UI and logs. Before verification the UI shows only which fields were received (U-2). |
| X-4 | Output check (a tripwire): before verification, a reply containing any claim's sensitive values (claim id, document names, amounts, dates) is replaced with fallback text and logged. In any phase, a full date of birth or phone number may not appear. The real protection is D-2 and G-2; this check only catches surprises. |
| X-5 | The API key lives only in the browser session (`st.session_state`) or a local `.env`. It never goes into URLs, logs or the trace. `.env` is ignored by git and Docker. |
| X-6 | `@st.cache_resource` caches only read-only data. Model clients are created per session. |

---

## 14. Configuration and model connection

| ID | Rule |
|---|---|
| K-1 | Settings come from real environment variables first, then the project's `.env`, then defaults. Empty values in `.env` are ignored. `.env` is read again on every request, so edits apply without a restart and removed lines stop applying. In the UI, a key, base URL or model typed in the sidebar takes priority over all of these (U-7). |
| K-2 | Any OpenAI-compatible endpoint works. With an empty base URL and a key starting with `gsk_`, the Groq endpoint is used. |
| K-3 | If the model is still the built-in default (`gpt-4.1-mini`) and the key belongs to another known provider, that provider's default is used instead (Groq: `openai/gpt-oss-120b`). A model set by the user or in `.env` is never replaced. |
| K-4 | Extraction and replies can use different models (`EXTRACT_MODEL`, `RESPONSE_MODEL`); both default to `MODEL`. |

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | none | Can also be entered in the sidebar |
| `OPENAI_BASE_URL` | OpenAI | Any compatible endpoint; Groq keys are detected |
| `MODEL` / `EXTRACT_MODEL` / `RESPONSE_MODEL` | `gpt-4.1-mini` | See K-3 and K-4 |
| `DEMO_TODAY` | unset (`2026-02-15` in Docker) | Real date when unset |
| `DATA_DIR` | `insurance_claims/fixtures` | Reads the provided data directly |
| Thresholds | 3 failed verifications; off-topic offer at 3, handoff at 4; refusals at 3 and 4; 4 turns without progress; anger for 2 turns | `config.py`, `policy.py` |

---

## 15. SessionState (main fields)

```python
class SessionState(BaseModel):
    session_id: str
    phase: Phase = Phase.VERIFY_ID
    turn: int = 0
    awaiting: Awaiting = Awaiting.NOTHING            # what the agent last asked; decides how yes/no is read
    # identity: actor / subject / authorization
    actor_type: Literal["policyholder", "representative"] = "policyholder"
    actor_name: str | None = None
    identity_claims: dict[str, str] = {}             # normalized values, only ever shown masked
    id_type_stated: str | None = None
    policy_number: str | None = None
    corrections: list[Correction] = []
    last_verify_fingerprint: str | None = None
    subject_party_id: str | None = None              # set only after verification / consent
    pending_party_id: str | None = None              # policyholder matched, waiting for consent
    identity_locked: bool = False
    consent_status: Literal["not_required", "pending", "approved", "timeout"] = "not_required"
    consent_checks: int = 0
    consent_scenario: str = "default"
    # counters
    verify_failures: int = 0
    gate_refusals: dict[str, int] = {}
    no_progress_turns: int = 0
    off_topic_streak: int = 0
    handoff_offered: bool = False
    escalation_level: int = 0
    anger_streak: int = 0
    abuse_count: int = 0
    last_emotion: EmotionSignal | None = None
    # memory across phases
    intent: Intent | None = None
    case_query: CaseQuery = CaseQuery()
    pending_questions: list[str] = []
    candidate_case_ids: list[str] = []
    resolved_case_id: str | None = None
    case_presented: bool = False
    # wrap-up
    discussed_facts: list[Fact] = []
    pending_followup: bool = False
    email_status: EmailStatus = EmailStatus.NOT_OFFERED
    email_reconfirmed: bool = False
    outbox: list[OutboxEmail] = []
    handoff: HandoffRecord | None = None
    # conversation
    history: list[Turn] = []                         # masked
    trace: list[TurnTrace] = []
```

---

## 16. Actions

| Phase | Actions |
|---|---|
| VERIFY_ID | `ASK_ID` `ID_MISMATCH` `EXPLAIN_GATE` `OFFER_ALT_FIELDS` `VERIFIED` `ASK_ACTOR_NAME` `REQUEST_CONSENT` `CONSENT_PENDING` |
| RESOLVE_INTENT | `ASK_INTENT` `CONFIRM_CASE` `DISAMBIGUATE_CASE` `NO_MATCHING_CASE` `NO_CASES_ON_FILE` `CASE_RESOLVED` |
| PROCESS_CASE | `PRESENT_CASE` `ANSWER_FOLLOWUP` `ANSWER_UNKNOWN` `OFFER_DOC_ALTERNATIVES` `ASK_ANYTHING_ELSE` |
| POST_PROCESS | `OFFER_EMAIL` `RECONFIRM_EMAIL` `EMAIL_SENT` `EMAIL_SKIPPED` `CLOSE` |
| Any phase | `DEFLECT_OFF_TOPIC` `OFFER_HANDOFF` `HANDOFF` `OTHER_PERSON_LOCKED` `CLARIFY` `TRANSITION` (internal: changes phase, says nothing) |
| Prefaces | `ACK_EMOTION` `ACK_HINT` `DEFLECT` `SMALLTALK` `THANKS` `ENGLISH_ONLY` |

Priority: handoff and identity lock first, then off-topic handling, then the phase's own action. Emotion and stray off-topic remarks only become a preface.

---

## 17. Test UI

| ID | Rule |
|---|---|
| U-1 | The UI only displays. Every decision is made by `handle_turn` and `policy`. |
| U-2 | Before verification, the identity card and sidebar show only which fields were received, and the claim card always shows Locked with nothing about any claim. Masked values, the account and the current claim id appear only after verification. |
| U-3 | Each reply has an expandable harness trace: phase change, actions, facts recorded, notes, and the masked extraction. |
| U-4 | Quick scenario buttons start a new session and send the first caller message. The representative scenarios also set the mock consent behavior. |
| U-5 | Suggested reply buttons are chosen from the current phase and what the agent is waiting for. They **never call the model**, and before verification they read no claim data. |
| U-6 | Demo date: three presets (before the deadline, after it, today) plus "Custom date". Only one date applies; the calendar appears only when the custom option is chosen. |
| U-7 | Connection fields in the sidebar start empty, with the current `.env` value shown as a hint. A value typed there wins for that browser session; an empty field falls back to `.env`, then to the defaults (K-2, K-3). The sidebar says where the key, model and endpoint came from. The mock outbox and the internal handoff summary are shown in their own panels. |
| U-8 | Everything inserted into HTML is escaped. Conversation text is shown with Streamlit's own components. |

---

## 18. Testing and acceptance

| ID | Rule |
|---|---|
| Q-1 | Automated tests (`pytest`, `tests/`) use a scripted `FakeLLM` and need no key. Each test names its rules. `scripts/test_report.py` writes `docs/test-report.md`. |
| Q-2 | Real-model scenarios: `scripts/run_scenarios.py` plays every scenario in `tests/scenarios.yaml` and checks only state and required or forbidden phrases, never exact wording. It runs a preflight check and supports `--only`, `--pause`, `--retries`, `--verbose`, `--report` and `--resume`. Each finished scenario is saved to `.scenario-progress.jsonl` straight away and the report is rewritten after every scenario. `--resume` skips scenarios that already passed with the same model and re-runs failed, rate-limited and missing ones. Any scenario with a rate-limited turn is marked RATE-LIMITED (inconclusive), even if its checks passed, because the model never saw that message. It is neither a pass nor a failure, and `--resume` runs it again. |
| Q-3 | Reports and test output use no emoji. Results are PASS, FAIL, RATE-LIMITED or SKIP. |
| Q-4 | Acceptance: in the reference case (Margaret) the caller is verified, CL-2048 is found, and the denial reason and missing documents are explained in one turn, followed later by the email offer; all automated tests pass; the pre-verification output check never fires; the UI accepts a key and shows the whole workflow; Docker starts with one command. |

---

## 19. Delivery

| Item | Details |
|---|---|
| Source | https://github.com/ChristinaPuth/Insurance-sop-agent |
| Live demo | Streamlit Community Cloud (URL in the README). Visitors enter their own key in the sidebar; the deployment stores no key. |
| Docker | `docker build -t insurance-sop-agent .` then `docker run -p 8501:8501 -e OPENAI_API_KEY=... insurance-sop-agent` |
| Local | `uv venv` and `uv pip install -r requirements.txt`, then `streamlit run app.py`; terminal chat with `python main.py` |
