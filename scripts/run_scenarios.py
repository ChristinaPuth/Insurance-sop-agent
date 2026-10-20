"""L3 scenario evaluation against a real model.

    OPENAI_API_KEY=gsk_... .venv/bin/python scripts/run_scenarios.py            # all scenarios
    .venv/bin/python scripts/run_scenarios.py --only golden_margaret angry_caller
    .venv/bin/python scripts/run_scenarios.py --report docs/scenario-report.md

Checks state and forbidden/required phrases, never exact wording (LLM output varies).
Base URL and model are inferred from a Groq key when not set.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.config import load_settings  # noqa: E402
from agent.data import load_data  # noqa: E402
from agent.llm_service import LLMError, OpenAILLM, default_base_url, default_model  # noqa: E402
from agent.orchestrator import handle_turn, start_session  # noqa: E402

GUARD_MARKERS = ("pre-verification", "echoed")
SCENARIO_TODAY = date(2026, 2, 15)   # the scenarios assume the demo date unless DEMO_TODAY or `today:` says otherwise


def get_path(obj, dotted: str):
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part)
    return obj.value if hasattr(obj, "value") else obj


def _plain(text: str) -> str:
    """Compare quotes and dashes loosely: models write ’ and — as often as ' and -."""
    return (text.lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"')
            .replace("\u201d", '"').replace("\u2014", "-").replace("\u2013", "-"))


def check_turn(spec: dict, state, reply: str) -> list[str]:
    fails = []
    low = _plain(reply)
    trace = state.trace[-1]
    for path, want in (spec.get("expect_state") or {}).items():
        got = get_path(state, path)
        if got != want:
            fails.append(f"state {path}: expected {want!r}, got {got!r}")
    for action in spec.get("steps_include") or []:
        if action not in trace.steps:
            fails.append(f"step {action} not in {trace.steps}")
    for bad in spec.get("reply_must_not") or []:
        if _plain(bad) in low:
            fails.append(f"reply contains forbidden {bad!r}")
    any_of = spec.get("reply_must_contain_any") or []
    if any_of and not any(_plain(x) in low for x in any_of):
        fails.append(f"reply has none of {any_of}")
    for note in trace.notes:
        if any(m in note for m in GUARD_MARKERS):
            fails.append(f"guard tripped: {note}")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "tests" / "scenarios.yaml"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--report", help="write a markdown report here")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to wait between scenarios (rate limits)")
    ap.add_argument("--retries", type=int, default=6, help="API retries per call; 429s are waited out")
    args = ap.parse_args()

    settings = load_settings()
    key = settings.api_key
    if not key:
        print("Set OPENAI_API_KEY (any OpenAI-compatible key).", file=sys.stderr)
        return 2
    base_url = settings.base_url or default_base_url(key)
    model_env = os.getenv("MODEL") or os.getenv("RESPONSE_MODEL")
    model = model_env or default_model(key) or settings.response_model
    llm = OpenAILLM(key, os.getenv("EXTRACT_MODEL") or model, model, base_url, max_retries=args.retries)
    default_today = settings.demo_today or SCENARIO_TODAY
    data = load_data(settings.data_dir)
    print(f"Preflight: checking the key against {base_url or 'api.openai.com'} with {model} ...", flush=True)
    try:                                   # fail fast: a bad key would make every scenario "fail" for no reason
        llm.extract("hello", {"phase": "VERIFY_ID"})
    except LLMError as exc:
        if exc.rate_limited:
            print(f"Preflight hit the provider's rate limit ({exc}). The key works; the quota is used up for now.\n"
                  "Wait a few minutes and retry. If it persists, the daily token quota is exhausted: check your "
                  "provider's limits page, or try another model with MODEL=...", file=sys.stderr)
        else:
            print(f"Preflight failed: {exc}. Check OPENAI_API_KEY / OPENAI_BASE_URL / MODEL.", file=sys.stderr)
        return 2

    scenarios = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]

    total_turns = sum(len(s["turns"]) for s in scenarios)
    print(f"Preflight OK. Running {len(scenarios)} scenarios ({total_turns} turns); one dot per finished turn.\n",
          flush=True)
    results = []
    run_started, done_turns = time.time(), 0
    for n, sc in enumerate(scenarios, 1):
        today = date.fromisoformat(sc["today"]) if sc.get("today") else default_today
        if args.pause and n > 1:
            time.sleep(args.pause)
        state = start_session("SES-L3" + sc["id"][:2].upper())
        state.consent_scenario = sc.get("consent_scenario", "default")
        transcript, fails = [], []
        started = time.time()
        print(f"[{n:>2}/{len(scenarios)}] {sc['id']:<30} ", end="", flush=True)
        for i, turn in enumerate(sc["turns"], 1):
            state, reply = handle_turn(state, turn["user"], llm, data, today, settings.thresholds)
            t = state.trace[-1]
            transcript.append((turn["user"], reply, t.steps, t.notes))
            fails += [f"turn {i}: {f}" for f in check_turn(turn, state, reply)]
            done_turns += 1
            print("." if not any("failed" in x for x in t.notes) else "!", end="", flush=True)
        ok = not fails
        limited = any("429" in note for *_, notes in transcript for note in notes)
        label = "PASS" if ok else ("RATE-LIMITED" if limited else "FAIL")
        results.append((sc, ok, fails, transcript, time.time() - started))
        print(f" {label}  {time.time() - started:4.1f}s   "
              f"(total {done_turns}/{total_turns} turns, {time.time() - run_started:.0f}s elapsed)", flush=True)
        for f in fails:
            print(f"      - {f}")
        if limited and not ok:
            print("      (hit the provider's rate limit; re-run later with --only " + sc["id"] + ")")
        elif args.verbose or not ok:
            for user, reply, steps, notes in transcript:
                print(f"      > {user}\n      < {reply}\n        {' → '.join(steps)} {notes or ''}")

    passed = sum(ok for _, ok, *_ in results)
    limited_ids = [sc["id"] for sc, ok, _, tr, _ in results
                   if not ok and any("429" in note for *_, notes in tr for note in notes)]
    print(f"\n{passed}/{len(results)} scenarios passed  (model={model}, base_url={base_url or 'openai'}, "
          f"today={default_today})")
    if limited_ids:
        print(f"{len(limited_ids)} hit the rate limit and are inconclusive. Re-run them with:\n"
              f"  .venv/bin/python scripts/run_scenarios.py --pause 20 --only {' '.join(limited_ids)}")

    if args.report:
        lines = [f"# Scenario report\n\nModel `{model}` · {passed}/{len(results)} passed\n"]
        for sc, ok, fails, transcript, secs in results:
            lines.append(f"## {'✅' if ok else '❌'} {sc['id']}\n\n{sc.get('description', '')}\n")
            for f in fails:
                lines.append(f"- **{f}**")
            for user, reply, steps, notes in transcript:
                lines.append(f"\n> **Caller:** {user}\n>\n> **Agent:** {reply}\n>\n> `{' → '.join(steps)}`"
                             + (f" ⚠️ {'; '.join(notes)}" if notes else ""))
            lines.append("")
        Path(args.report).write_text("\n".join(lines), encoding="utf-8")
        print(f"report written to {args.report}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
