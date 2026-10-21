# Test report

Generated 2026-10-20 20:28 · **111/111 passed** · 0.47s

Unit and workflow tests run against a scripted `FakeLLM` (no API key, deterministic). Real-model
conversations are covered separately by `scripts/run_scenarios.py` (see `scenario-report.md`).
The rule column refers to the numbered rules in [`SPEC.md`](SPEC.md).

| Area | Tests | Result |
|---|---|---|
| Identity verification (`test_verification.py`) | 20 | PASS 20/20 |
| Case matching (`test_case_resolver.py`) | 10 | PASS 10/10 |
| Fact, date and amount checks (`test_facts.py`) | 5 | PASS 5/5 |
| FAQ guideline templates (`test_guidance.py`) | 12 | PASS 12/12 |
| Emotion, persuasion ladder, scope (`test_emotion.py`) | 13 | PASS 13/13 |
| Representative and authorization (`test_consent.py`) | 9 | PASS 9/9 |
| End-to-end workflow (`test_workflow.py`) | 35 | PASS 35/35 |
| UI suggested replies (`test_ui_suggestions.py`) | 7 | PASS 7/7 |

## Identity verification

`tests/test_verification.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | three matching fields verify | V-1 |
| PASS | two fields are not enough | V-1 |
| PASS | policy number does not count | V-2 |
| PASS | all wrong fails | V-1 |
| PASS | three right one wrong fails | V-1 (no conflicts) |
| PASS | fields from different people fail | V-1 (same record) |
| PASS | near identical phone is not margaret | V-5 |
| PASS | national id holder verifies | V-7 |
| PASS | wrong id type is neither match nor conflict | V-7 |
| PASS | aliases from data | V-3, V-6, V-11 |
| PASS | fingerprint changes only with values | V-9 |
| PASS | dob normalization[1985-03-15-1985-03-15] | E-1 |
| PASS | dob normalization[March 15th, 1985-1985-03-15] | E-1 |
| PASS | dob normalization[03/15/1985-1985-03-15] | E-1 |
| PASS | phone normalization[(650) 521-2836-+16505212836] | E-1 |
| PASS | phone normalization[650-521-2836-+16505212836] | E-1 |
| PASS | phone normalization[+1 650 521 2836-+16505212836] | E-1 |
| PASS | dotenv loading never overrides env | K-1 |
| PASS | dotenv edits apply without restart | K-1 |
| PASS | site settings win then env then defaults | K-1, K-2, K-3, U-7 |

## Case matching

`tests/test_case_resolver.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | specific unique hint resolves | C-3 |
| PASS | month without status is ambiguous | C-5: recency never picks |
| PASS | vague single candidate is confirmed | C-4 |
| PASS | no clue and no intent asks | C-4 |
| PASS | vague intent with many claims disambiguates | C-4/C-5 |
| PASS | claim id of someone else is not found | C-1, D-2 |
| PASS | own claim id resolves | C-1 |
| PASS | no cases on file | C-6 |
| PASS | repo never exposes other parties | D-2 |
| PASS | denial question alone narrows to denied | C-2, C-4 |

## Fact, date and amount checks

`tests/test_facts.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | deadline before and after | F-5, F-6 |
| PASS | unknown fact ids are dropped | T-3 (1) |
| PASS | claimed fact must appear in text | T-3 (2) |
| PASS | wrong amount or date is rejected | T-6 |
| PASS | dates from step params are allowed | T-6 (candidate lists) |

## FAQ guideline templates

`tests/test_guidance.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | doc names match guideline keys | D-4 |
| PASS | topics fill templates[submission method-member portal] | F-1 |
| PASS | topics fill templates[processing time-usually less than a week] | F-1 |
| PASS | topics fill templates[submission timing-within a week] | F-1 |
| PASS | topics fill templates[receipt confirmation-intake delay] | F-1 |
| PASS | topics fill templates[file format-clear, complete] | F-1 |
| PASS | file format adds document specific guidance | F-2 |
| PASS | timing template dropped after deadline | F-6 over F-5 |
| PASS | doc alternatives | F-9 |
| PASS | unknown document uses default alternative | D-4 fallback |
| PASS | no topic falls back | F-4 |
| PASS | every extractor topic maps to a guideline entry | F-1 |

## Emotion, persuasion ladder, scope

`tests/test_emotion.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | ladder climbs and hands off | M-2, M-5 |
| PASS | cooperation steps down | M-4 |
| PASS | declining the human keeps verifying | M-11 |
| PASS | refusing one field is not a gate refusal | M-6 |
| PASS | anger twice at max offers human | M-5 |
| PASS | distress offers human | M-5 |
| PASS | second abuse hands off | M-5, S-10 |
| PASS | ack emotion not repeated | M-7 |
| PASS | out of role redirects | O-1, O-6 |
| PASS | non english is not counted | G-5, O-6 |
| PASS | handoff text is fixed | H-4 |
| PASS | followup after email sent is flagged | P-7 |
| PASS | faq answer recorded for email | F-1, P-5 |

## Representative and authorization

`tests/test_consent.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | representative waits for consent then gets the claim | A-2, A-3, D-2 |
| PASS | subject is not reachable while pending | D-2 |
| PASS | consent timeout hands off | A-3, S-2 |
| PASS | unlisted caller is handed off | A-2 |
| PASS | missing caller name is asked | A-2 |
| PASS | caller name does not count as subject pii | A-2 |
| PASS | email goes to policyholder | A-6 |
| PASS | policyholder turning into representative after verification | A-4 |
| PASS | switching to representative before verification keeps fields | A-4 |

## End-to-end workflow

`tests/test_workflow.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | golden path | S-1, S-3, S-12, C-3, P-2, P-5, S-9 |
| PASS | history is masked | X-1 |
| PASS | hint remembered but nothing disclosed before verification | E-3, C-8 |
| PASS | angry caller is not let through | M-2, M-8, E-4 |
| PASS | pending question answered after verification | E-4 |
| PASS | failed attempts count once per new attempt | V-9, V-10, S-2 |
| PASS | ambiguous month asks which claim | C-5 |
| PASS | other persons claim id | C-1 |
| PASS | no cases ends without email | S-4, P-2, S-9 |
| PASS | decline then change mind | P-1 |
| PASS | followup while email offered reasks | S-7, P-8 |
| PASS | off topic offer then handoff | O-1, O-3, S-10 |
| PASS | smalltalk is not counted | O-1 |
| PASS | wants human is immediate | H-1 |
| PASS | refused field offers alternatives | M-6 |
| PASS | llm reply with wrong amount falls back | T-6 |
| PASS | llm reply missing must state gets appended | T-4 |
| PASS | pre verification reply leak is blocked | X-4 |
| PASS | input state is not mutated | G-4 |
| PASS | extraction failure clarifies | T-1 |
| PASS | rejected key reports setup problem | T-9 |
| PASS | rate limit asks to resend | T-9 |
| PASS | other persons claim after verification | A-5 |
| PASS | followup context carries the question | T-8, F-7 |
| PASS | other person keyword safety net | A-5, E-7 |
| PASS | other person rule ignores own claims | E-7 |
| PASS | off topic question is not made relevant by being a question | O-1 |
| PASS | refused field keyword safety net | M-6, E-7 |
| PASS | refused field rule | E-7 |
| PASS | refused field name from model is normalized | M-6, E-7: model said "ssn" or left the field empty |
| PASS | field refusal tagged as verification refusal | M-6, E-7: model over-reads one field as all |
| PASS | field refusal beats a skip flag | M-6: model flagged both "skip" and one named field |
| PASS | question during email offer is answered even if read as unclear | S-7, P-8 |
| PASS | setup errors say what to fix | T-9 |
| PASS | groq model name without prefix is corrected | K-3 |

## UI suggested replies

`tests/test_ui_suggestions.py`

| Result | Test | Rule / note |
|---|---|---|
| PASS | fresh session offers identity and edge cases | U-5 |
| PASS | partial identity suggests only whats missing | U-5 |
| PASS | other caller gets no margaret details | U-5 |
| PASS | processing phase offers followups | U-5 |
| PASS | email offer and terminal states | U-5 |
| PASS | consent pending suggestions | U-5, A-7 |
| PASS | guide table steps are offered as suggestions | U-5, U-9: the in-app guide stays accurate |
