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
    return LLMClient(FakeSettings(), recorder, client=fake), recorder


def test_extract_validates_and_retries_once_with_the_error() -> None:
    bad, good = fixture("llm/extract_replies")["replies"]
    fake = FakeLLM(bad, good)
    client, recorder = make(fake)

    result = client.extract(Round, "Extract the round.", "Lumen Ledger raised $120M.")

    assert result == Round(company="Lumen Ledger", round_usd=120_000_000)
    first, second = fake.requests
    assert first["tools"][0]["input_schema"] == Round.model_json_schema()
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert first["model"] == "claude-sonnet-5-5"
    assert "previous answer was invalid" not in first["messages"][0]["content"]
    assert "round_usd" in second["messages"][0]["content"]
    assert [(c.unit_type, c.units) for c in recorder.calls] == [
        ("input_tokens", 100), ("output_tokens", 20)] * 2
    assert all(c.provider == "llm" and c.kind == "llm" for c in recorder.calls)


def test_extract_gives_up_after_one_retry() -> None:
    client, _ = make(FakeLLM({"company": "x"}, "I'd rather explain in prose."))
    with pytest.raises(LLMError):
        client.extract(Round, "s", "p")


def test_write_returns_text_with_model_override() -> None:
    fake = FakeLLM("Dear founder,")
    client, _ = make(fake)
    assert client.write("s", "p", model="claude-haiku-5-5") == "Dear founder,"
    assert fake.requests[0]["model"] == "claude-haiku-5-5"
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
