"""Terminal chat with the agent, for demos and debugging.

    python main.py              # interactive
    python main.py --trace      # also print the harness trace after each turn
"""
from __future__ import annotations

import argparse
import json
import sys

from agent.config import get_today, load_settings
from agent.data import load_data
from agent.llm_service import OpenAILLM, resolve_connection
from agent.orchestrator import handle_turn, start_session
from agent.schemas import Phase


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    if not settings.api_key:
        print("Set OPENAI_API_KEY (see .env.example).", file=sys.stderr)
        return 1
    conn = resolve_connection(settings)
    llm = OpenAILLM(conn.api_key, settings.extract_model if settings.model_configured else conn.model,
                    conn.model, conn.base_url)
    data, today = load_data(settings.data_dir), get_today(settings)

    state = start_session("SES-CLI0")
    print(f"[today = {today}]\nAgent: {state.history[0].text}")
    while state.phase not in (Phase.COMPLETE, Phase.HANDOFF):
        try:
            msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        state, reply = handle_turn(state, msg, llm, data, today, settings.thresholds)
        print(f"Agent: {reply}")
        if args.trace:
            print("  trace:", json.dumps(state.trace[-1].model_dump(mode="json"), ensure_ascii=False))
    print(f"[ended in {state.phase.value}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
