"""Runtime configuration (SPEC §16). Only entry points read the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    thresholds: Thresholds = Thresholds()


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from a local .env (git- and docker-ignored).
    Real environment variables always win; empty values are skipped."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    load_dotenv()
    model = os.getenv("MODEL", "gpt-4.1-mini")
    today = os.getenv("DEMO_TODAY")
    return Settings(
        api_key=os.getenv("OPENAI_API_KEY") or None,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        extract_model=os.getenv("EXTRACT_MODEL", model),
        response_model=os.getenv("RESPONSE_MODEL", model),
        data_dir=Path(os.getenv("DATA_DIR", ROOT / "insurance_claims" / "fixtures")),
        demo_today=date.fromisoformat(today) if today else None,
    )


def get_today(settings: Settings) -> date:
    """D-3: DEMO_TODAY wins, else the real date. Called only at entry points."""
    return settings.demo_today or date.today()
