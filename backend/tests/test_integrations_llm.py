import httpx
import pytest
from pydantic import BaseModel

from app.integrations.errors import LLMError
from app.integrations.llm import FakeLLM, LLMClient, quote_check
from app.integrations.recorder import InMemoryRecorder
from tests.test_integrations_crustdata import FakeSettings, fixture


class Round(BaseModel):
    company: str
    round_usd: int


def make(fake: FakeLLM) -> tuple[LLMClient, InMemoryRecorder]:
    recorder = InMemoryRecorder()
    return LLMClient(FakeSettings(), recorder, fake, sleep=lambda _: None), recorder


def test_extract_validates_and_retries_once_with_the_error() -> None:
    bad, good = fixture("llm/extract_replies")["replies"]
    fake = FakeLLM(bad, good)
    client, recorder = make(fake)

    result = client.extract(Round, "Extract the round.", "Lumen Ledger raised $120M.")

    assert result == Round(company="Lumen Ledger", round_usd=120_000_000)
    first, second = fake.requests
    assert first["tools"][0]["function"]["parameters"] == Round.model_json_schema()
    assert first["tool_choice"] == "auto" and first["parallel_tool_calls"] is False
    assert first["model"] == "anthropic/claude-sonnet-5.5"
    assert first["messages"][0]["role"] == "system"
    assert "previous answer was invalid" not in first["messages"][1]["content"]
    assert "round_usd" in second["messages"][1]["content"]
    assert [(c.unit_type, c.units) for c in recorder.calls] == [
        ("input_tokens", 120), ("output_tokens", 40)] * 2
    assert all(c.provider == "llm" and c.kind == "llm" for c in recorder.calls)


def test_extract_gives_up_after_one_retry() -> None:
    client, _ = make(FakeLLM({"company": "x"}, "I'd rather explain in prose."))
    with pytest.raises(LLMError):
        client.extract(Round, "s", "p")


def test_write_returns_text_with_model_override() -> None:
    fake = FakeLLM("Dear founder,")
    client, _ = make(fake)
    assert client.write("s", "p", model="anthropic/claude-haiku-5.5") == "Dear founder,"
    assert fake.requests[0]["model"] == "anthropic/claude-haiku-5.5"
    assert "tools" not in fake.requests[0]


@pytest.mark.parametrize(
    ("haystack", "quote", "expected"),
    [
        ("Revenue grew  to $4M\nin 2025.", "revenue grew to $4m in 2025", True),
        ("the “best” team — period", '"best" team - period', True),
        ("it’s growing", "it's growing", True),
        ("ARR is $4M", "ARR is $5M", False),
        ("anything", "   ", False),
    ],
)
def test_quote_check(haystack: str, quote: str, expected: bool) -> None:
    assert quote_check(haystack, quote) is expected


def test_auth_header_and_upstream_error_in_a_200() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"error": {"message": "provider down", "code": 502}})

    client = LLMClient(FakeSettings(), InMemoryRecorder(), httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="provider down"):
        client.write("s", "p")
    assert seen[0].headers["authorization"] == "Bearer or-test-key"
    assert str(seen[0].url) == "https://openrouter.test/api/v1/chat/completions"


def test_retries_5xx_then_gives_up() -> None:
    sleeps: list[float] = []
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    client = LLMClient(FakeSettings(), InMemoryRecorder(), transport, sleep=sleeps.append)
    with pytest.raises(LLMError, match="unavailable"):
        client.write("s", "p")
    assert sleeps == [1.0, 2.0, 4.0]
