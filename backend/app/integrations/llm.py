"""LLM client: structured extraction into Pydantic models, prose, and quote checks."""

import re
import unicodedata
from collections import deque
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import anthropic
from anthropic.types import Message
from pydantic import BaseModel, ValidationError

from app.integrations import IntegrationSettings
from app.integrations.errors import LLMError
from app.integrations.recorder import Recorder
from app.models.enums import Provider, SourceKind, UnitType

MAX_TOKENS = 16000
TOOL_NAME = "submit"


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
    """Claude via the Anthropic SDK; every call is recorded with its token counts."""

    def __init__(
        self,
        settings: IntegrationSettings,
        recorder: Recorder,
        client: Any = None,
        run_id: UUID | None = None,
    ) -> None:
        self.settings, self.recorder, self.run_id = settings, recorder, run_id
        # Any: the SDK's overloaded `messages.create` can't be matched by a Protocol,
        # and tests pass `FakeLLM`.
        self.client: Any = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def extract[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, model: str | None = None
    ) -> T:
        """Get one `submit` tool call whose input validates as `schema`; retry once on error."""
        tool = {
            "name": TOOL_NAME,
            "description": f"Submit the {schema.__name__} result.",
            "input_schema": schema.model_json_schema(),
        }
        # Forced tool_choice (any/tool) is a 400 on Sonnet 5.5 / Opus 5.5, so the call is
        # steered by the prompt with auto + one call at most, then validated here.
        system = f"{system}\n\nAnswer only by calling the `{TOOL_NAME}` tool exactly once."
        error = ""
        for _ in range(2):
            content = prompt + (f"\n\nYour previous answer was invalid: {error}" if error else "")
            message = self._create(
                model, system, content,
                tools=[tool], tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            )
            block = next((b for b in message.content if b.type == "tool_use"), None)
            if block is None:
                error = f"no `{TOOL_NAME}` tool call (stop_reason={message.stop_reason})"
                continue
            try:
                return schema.model_validate(block.input)
            except ValidationError as exc:
                error = str(exc)
        raise LLMError(f"extract {schema.__name__} failed: {error}")

    def write(self, system: str, prompt: str, model: str | None = None) -> str:
        """Free text (memo, outreach)."""
        message = self._create(model, system, prompt)
        if message.stop_reason == "refusal":
            raise LLMError("model refused")
        return "".join(b.text for b in message.content if b.type == "text")

    def _create(self, model: str | None, system: str, prompt: str, **extra: Any) -> Message:
        model = model or self.settings.llm_model
        request = {"model": model, "system": system, "prompt": prompt}
        message: Message = self.client.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": prompt}], **extra,
        )
        response = message.model_dump(mode="json", include={"content", "stop_reason", "usage"})
        # The ledger has one unit type per row, so tokens in and out are two rows.
        for units, unit_type in (
            (message.usage.input_tokens, UnitType.input_tokens),
            (message.usage.output_tokens, UnitType.output_tokens),
        ):
            self.recorder.record(
                provider=Provider.llm, endpoint="/v1/messages", request=request,
                response=response, units=float(units), unit_type=unit_type, cached=False,
                run_id=self.run_id, kind=SourceKind.llm,
            )
        return message


class FakeLLM:
    """Stand-in for `anthropic.Anthropic`: pops one queued reply per `messages.create`.

    A dict becomes a `submit` tool call with that input; a str becomes a text reply.
    Requests are kept in `requests`.
    """

    def __init__(self, *replies: dict[str, Any] | str) -> None:
        self.replies: deque[dict[str, Any] | str] = deque(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def queue(self, *replies: dict[str, Any] | str) -> None:
        self.replies.extend(replies)

    def _create(self, **kwargs: Any) -> Message:
        self.requests.append(kwargs)
        reply = self.replies.popleft()
        if isinstance(reply, str):
            block: dict[str, Any] = {"type": "text", "text": reply}
            stop = "end_turn"
        else:
            block = {"type": "tool_use", "id": "toolu_fake", "name": TOOL_NAME, "input": reply}
            stop = "tool_use"
        return Message.model_validate({
            "id": "msg_fake", "type": "message", "role": "assistant", "model": kwargs["model"],
            "content": [block], "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })
