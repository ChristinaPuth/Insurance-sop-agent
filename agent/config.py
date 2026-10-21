"""Runtime configuration (SPEC §16). Only entry points read the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gpt-4.1-mini"      # OpenAI default; other providers pick their own (llm_service.default_model)


@dataclass(frozen=True)
class Thresholds:
    verify_failures: int = 3        # V-9
    off_topic_offer: int = 3        # O-3: offer handoff
    off_topic_handoff: int = 4      # O-3: handoff after the offer
    history_window: int = 6         # turns of masked history sent to the LLM


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str | None
    extract_model: str
    response_model: str
    data_dir: Path
    demo_today: date | None
    model_configured: bool = False    # MODEL / RESPONSE_MODEL set explicitly (not the built-in default)
    thresholds: Thresholds = Thresholds()


_FROM_DOTENV: dict[str, str] = {}     # keys this module put into os.environ, so a re-read can update them


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip('"').strip("'")
        if value:
            out[key] = value
    return out


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from a local .env (git- and docker-ignored). Safe to call on every request:
    edits to the file take effect without a restart, and lines that were removed or emptied are dropped.
    Variables set in the real environment (shell, Docker -e, hosting secrets) always win (K-1)."""
    fresh = _parse_dotenv(path)
    for key in list(_FROM_DOTENV):
        if key not in fresh and os.environ.get(key) == _FROM_DOTENV[key]:
            os.environ.pop(key, None)
            del _FROM_DOTENV[key]
    for key, value in fresh.items():
        if key in os.environ and key not in _FROM_DOTENV:
            continue                                   # set outside .env: leave it alone
        os.environ[key] = value
        _FROM_DOTENV[key] = value


def load_settings() -> Settings:
    load_dotenv()
    configured = bool(os.getenv("MODEL") or os.getenv("RESPONSE_MODEL"))
    model = os.getenv("MODEL", DEFAULT_MODEL)
    today = os.getenv("DEMO_TODAY")
    return Settings(
        api_key=os.getenv("OPENAI_API_KEY") or None,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        extract_model=os.getenv("EXTRACT_MODEL", model),
        response_model=os.getenv("RESPONSE_MODEL", model),
        data_dir=Path(os.getenv("DATA_DIR", ROOT / "insurance_claims" / "fixtures")),
        demo_today=date.fromisoformat(today) if today else None,
        model_configured=configured,
    )


def get_today(settings: Settings) -> date:
    """D-3: DEMO_TODAY wins, else the real date. Called only at entry points."""
    return settings.demo_today or date.today()
