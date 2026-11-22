"""LLM client: structured extraction into Pydantic models, prose, and quote checks.

Talks to OpenRouter's OpenAI-compatible chat API (Claude Sonnet 5.5 via BYOK) over httpx.
"""

import json
import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations import IntegrationSettings
from app.integrations.errors import LLMError
from app.integrations.recorder import Recorder
from app.models.enums import Provider, SourceKind, UnitType

MAX_TOKENS = 16000
TOOL_NAME = "submit"
ENDPOINT = "/chat/completions"
BACKOFF = (1.0, 2.0, 4.0)
TIMEOUT_SECONDS = 120.0


_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-",
})


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_check(haystack: str, quote: str) -> bool:
    """True if `quote` appears in `haystack`, ignoring whitespace, quote/dash style and case."""
    needle = _normalise(quote)
    return bool(needle) and needle in _normalise(haystack)


class LLMClient:
    """Chat completions via OpenRouter; every call is recorded with its token counts."""

    def __init__(
        self,
        settings: IntegrationSettings,
        recorder: Recorder,
        transport: httpx.BaseTransport | None = None,
        run_id: UUID | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings, self.recorder, self.run_id, self.sleep = settings, recorder, run_id, sleep
        self.http = httpx.Client(
            base_url=settings.openrouter_base_url,
            headers={
                "authorization": f"Bearer {settings.openrouter_api_key or ''}",
                "x-title": "Scout",
            },
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        )

    def extract[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, model: str | None = None
    ) -> T:
        """Get one `submit` tool call whose arguments validate as `schema`; retry once."""
        tool = {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": f"Submit the {schema.__name__} result.",
                "parameters": schema.model_json_schema(),
            },
        }
        # forcing a named tool is rejected for some Claude models, so steer with the prompt
        # and validate; a missing or invalid call gets one retry with the reason
        system = f"{system}\n\nAnswer only by calling the `{TOOL_NAME}` tool exactly once."
        error = ""
        for _ in range(2):
            content = prompt + (f"\n\nYour previous answer was invalid: {error}" if error else "")
            message, finish = self._create(
                model, system, content,
                tools=[tool], tool_choice="auto", parallel_tool_calls=False,
            )
            calls = [c for c in message.get("tool_calls") or [] if
                     c.get("function", {}).get("name") == TOOL_NAME]
            if not calls:
                error = f"no `{TOOL_NAME}` tool call (finish_reason={finish})"
                continue
            try:
                return schema.model_validate_json(calls[0]["function"]["arguments"])
            except ValidationError as exc:
                error = str(exc)
        raise LLMError(f"extract {schema.__name__} failed: {error}")

    def write(self, system: str, prompt: str, model: str | None = None) -> str:
        """Free text (memo, outreach)."""
        message, finish = self._create(model, system, prompt)
        if finish == "content_filter":
            raise LLMError("model refused")
        return str(message.get("content") or "")

    def _create(
        self, model: str | None, system: str, prompt: str, **extra: Any
    ) -> tuple[dict[str, Any], str | None]:
        body = {
            "model": model or self.settings.llm_model,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            **extra,
        }
        data = self._post(body)
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        response = {"choice": choice, "usage": usage, "model": data.get("model")}
        # the ledger has one unit type per row, so tokens in and out are two rows
        for units, unit_type in (
            (usage.get("prompt_tokens", 0), UnitType.input_tokens),
            (usage.get("completion_tokens", 0), UnitType.output_tokens),
        ):
            self.recorder.record(
                provider=Provider.llm, endpoint=ENDPOINT, request=body,
                response=response, units=float(units), unit_type=unit_type, cached=False,
                run_id=self.run_id, kind=SourceKind.llm,
            )
        return choice.get("message") or {}, choice.get("finish_reason")

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        failure = ""
        for attempt in range(len(BACKOFF) + 1):
            try:
                response = self.http.post(ENDPOINT, json=body)
            except httpx.TransportError as exc:
                failure = repr(exc)
            else:
                if response.status_code < 400:
                    data: dict[str, Any] = response.json()
                    if "error" in data:  # OpenRouter can report upstream errors with a 200
                        raise LLMError(f"OpenRouter error: {data['error']}")
                    return data
                if response.status_code != 429 and response.status_code < 500:
                    raise LLMError(f"OpenRouter HTTP {response.status_code}: {response.text}")
                failure = f"HTTP {response.status_code}"
            if attempt < len(BACKOFF):
                self.sleep(BACKOFF[attempt])
        raise LLMError(f"OpenRouter unavailable: {failure}")


class FakeLLM(httpx.MockTransport):
    """Transport for tests: pops one queued reply per request.

    A dict becomes a `submit` tool call with those arguments; a str becomes a text reply.
    Request bodies are kept in `requests`.
    """

    def __init__(self, *replies: dict[str, Any] | str) -> None:
        self.replies: deque[dict[str, Any] | str] = deque(replies)
        self.requests: list[dict[str, Any]] = []
        super().__init__(self._handle)

    def queue(self, *replies: dict[str, Any] | str) -> None:
        self.replies.extend(replies)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        reply = self.replies.popleft()
        if isinstance(reply, dict):
            message: dict[str, Any] = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_{len(self.requests)}",
                    "type": "function",
                    "function": {"name": TOOL_NAME, "arguments": json.dumps(reply)},
                }],
            }
            finish = "tool_calls"
        else:
            message, finish = {"role": "assistant", "content": reply}, "stop"
        return httpx.Response(200, json={
            "model": self.requests[-1]["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        })
