import json

from arqen.core.contracts import Message, ProviderResponse, ToolRequest, Usage
from arqen.core.engine import ConversationEngine
from arqen.core.provider_metrics import ProviderMetrics
from arqen.providers.cloud import OpenAICompatibleProvider
from arqen.tools.base import Tool
from arqen.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Echoes the given text."
    arguments_schema = {"text": str}

    def run(self, arguments):
        return f"echo: {arguments['text']}"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return registry


def test_usage_adds_up_and_shrugs_off_junk() -> None:
    usage = Usage()
    usage.add({"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.001})
    usage.add({"prompt_tokens": 50, "completion_tokens": 5, "cost": 0.0005})
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (150, 25, 175)
    assert usage.cost == 0.0015

    usage.add(None)
    usage.add({"cost": "inte ett tal"})
    usage.add("inte ens en dict")
    assert usage.total_tokens == 175
    assert usage.cost == 0.0015


def test_a_streamed_response_carries_its_usage_through() -> None:
    provider = OpenAICompatibleProvider("https://example.invalid", "m", 1.0, "k", "test")
    response = provider._build("hej", [], {"prompt_tokens": 17, "completion_tokens": 18, "cost": 2.3e-05})
    assert response.usage == {"prompt_tokens": 17, "completion_tokens": 18, "cost": 2.3e-05}


class TwoCallProvider:
    """One tool call, then an answer -- each reporting its own usage."""

    supports_tools = True
    provider_name = "test"
    model = "test"

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, messages: list[Message], tools=None) -> ProviderResponse:
        self.calls += 1
        usage = {"prompt_tokens": 1000, "completion_tokens": 50, "cost": 0.002}
        if self.calls == 1:
            return ProviderResponse(
                content="",
                tool_request=ToolRequest(name="echo", arguments={"text": "hej"}, call_id="call_1"),
                tool_calls=({"id": "call_1", "function": {"name": "echo", "arguments": '{"text": "hej"}'}},),
                usage=usage,
            )
        return ProviderResponse(content="klart", usage=usage)


def test_a_turn_sums_every_call_it_took(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    engine = ConversationEngine(provider=TwoCallProvider(), tools=_registry())
    engine.respond("kör echo med hej")
    assert engine.turn_usage.total_tokens == 2 * 1050, "both provider calls must be counted"
    assert engine.turn_usage.cost == 0.004


class AnswerOnlyProvider:
    """One call per turn, so a turn's figure is one response and no more."""

    supports_tools = True
    provider_name = "test"
    model = "test"

    def respond(self, messages: list[Message], tools=None) -> ProviderResponse:
        return ProviderResponse(
            content="klart",
            usage={"prompt_tokens": 1000, "completion_tokens": 50, "cost": 0.002},
        )


def test_the_turn_resets_but_the_session_keeps_counting(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    engine = ConversationEngine(provider=AnswerOnlyProvider(), tools=_registry())
    engine.respond("första")
    assert engine.turn_usage.total_tokens == 1050
    engine.respond("andra")
    assert engine.turn_usage.total_tokens == 1050, "a new turn starts from zero"
    assert engine.session_usage.total_tokens == 2100, "the session keeps both"


def test_metrics_read_a_file_written_before_tokens_were_tracked(tmp_path) -> None:
    path = tmp_path / "provider_metrics.json"
    path.write_text(
        json.dumps({"openrouter/m": {"requests": 4, "successes": 4, "errors": 0,
                                     "fallbacks": 0, "total_ms": 900.0}}),
        encoding="utf-8",
    )
    metrics = ProviderMetrics(path)
    assert metrics.totals().total_tokens == 0

    metrics.record("openrouter", "m", 120.0, True, False, Usage(prompt_tokens=30, completion_tokens=7, cost=0.01))
    stored = json.loads(path.read_text(encoding="utf-8"))["openrouter/m"]
    assert stored["requests"] == 5, "the old counters must survive"
    assert (stored["prompt_tokens"], stored["completion_tokens"]) == (30, 7)
    assert metrics.totals().cost == 0.01


def test_totals_span_every_provider(tmp_path) -> None:
    metrics = ProviderMetrics(tmp_path / "m.json")
    metrics.record("openrouter", "a", 1.0, True, False, Usage(prompt_tokens=10, completion_tokens=1, cost=0.5))
    metrics.record("openai", "b", 1.0, True, False, Usage(prompt_tokens=20, completion_tokens=2, cost=0.25))
    totals = metrics.totals()
    assert totals.total_tokens == 33
    assert totals.cost == 0.75
