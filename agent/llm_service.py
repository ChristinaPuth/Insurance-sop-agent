"""LLM access (SPEC §3, T-1, T-2). Swappable: tests inject FakeLLM."""
from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import ValidationError

from .prompts import EXTRACT_SYSTEM, RESPOND_SYSTEM
from .schemas import AgentReply, ExtractionResult


class LLMError(Exception):
    """Wrapped error: never carries request headers or the API key (X-5)."""

    def __init__(self, message: str, config_problem: bool = False, rate_limited: bool = False):
        super().__init__(message)
        self.config_problem = config_problem   # bad key / URL / model: retrying won't help
        self.rate_limited = rate_limited       # provider quota (429): retrying later will help


# key prefix -> (base URL, a default model that exists on that provider)
KNOWN_KEY_PREFIXES = {"gsk_": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b")}


def default_base_url(api_key: str) -> str | None:
    """Pick the endpoint from a recognizable key prefix when the user left Base URL empty."""
    return next((v[0] for prefix, v in KNOWN_KEY_PREFIXES.items() if api_key.startswith(prefix)), None)


def default_model(api_key: str) -> str | None:
    return next((v[1] for prefix, v in KNOWN_KEY_PREFIXES.items() if api_key.startswith(prefix)), None)


class LLM(Protocol):
    def extract(self, message: str, context: dict[str, Any]) -> ExtractionResult: ...
    def respond(self, context: dict[str, Any]) -> AgentReply: ...


class OpenAILLM:
    """OpenAI or any OpenAI-compatible endpoint. One client per session (X-6)."""

    def __init__(self, api_key: str, extract_model: str, response_model: str, base_url: str | None = None,
                 max_retries: int = 2):
        from openai import OpenAI

        self.base_url = base_url or default_base_url(api_key)
        # the SDK backs off between retries and honours the provider's Retry-After on 429
        self._client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=30, max_retries=max_retries)
        self.extract_model = extract_model
        self.response_model = response_model

    def _json_call(self, model: str, system: str, user: str, temperature: float) -> dict[str, Any]:
        for attempt in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=model, temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                break
            except Exception as exc:  # noqa: BLE001 - re-raised without the original message (X-5)
                status = getattr(exc, "status_code", None)
                if status == 400 and attempt == 0:
                    continue        # JSON-mode providers return 400 when the model's JSON fails validation
                raise LLMError(f"API call failed ({type(exc).__name__}{f', {status}' if status else ''})",
                               config_problem=status in (401, 403, 404), rate_limited=status == 429) from None
        content = resp.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError("model returned invalid JSON") from exc

    def extract(self, message: str, context: dict[str, Any]) -> ExtractionResult:
        """T-1: one retry that quotes the validation error, then give up."""
        user = json.dumps({"context": context, "caller_message": message}, ensure_ascii=False)
        error = None
        for _ in range(2):
            prompt = user if error is None else f"{user}\n\nYour previous JSON was invalid: {error}. Fix it."
            raw = self._json_call(self.extract_model, EXTRACT_SYSTEM, prompt, temperature=0)
            try:
                return ExtractionResult.model_validate(raw)
            except ValidationError as exc:
                error = str(exc)[:500]
        raise LLMError("extraction failed validation twice")

    def respond(self, context: dict[str, Any]) -> AgentReply:
        raw = self._json_call(self.response_model, RESPOND_SYSTEM,
                              json.dumps(context, ensure_ascii=False, default=str), temperature=0.4)
        try:
            return AgentReply.model_validate(raw)
        except ValidationError as exc:
            raise LLMError("response failed validation") from exc


class FakeLLM:
    """Scripted extractions; `respond` fails so the orchestrator uses fallback text (T-2/T-7)."""

    def __init__(self, extractions: list[ExtractionResult | dict], replies: list[AgentReply | None] | None = None):
        self._extractions = [e if isinstance(e, ExtractionResult) else ExtractionResult.model_validate(e)
                             for e in extractions]
        self._replies = list(replies or [])
        self.respond_contexts: list[dict[str, Any]] = []

    def extract(self, message: str, context: dict[str, Any]) -> ExtractionResult:
        if not self._extractions:
            raise LLMError("no scripted extraction left")
        return self._extractions.pop(0)

    def respond(self, context: dict[str, Any]) -> AgentReply:
        self.respond_contexts.append(context)
        reply = self._replies.pop(0) if self._replies else None
        if reply is None:
            raise LLMError("fake LLM has no reply")
        return reply
