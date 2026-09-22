from arqen.core.contracts import Message, ProviderResponse
from arqen.core.engine import ConversationEngine, _leading_path
from arqen.providers.cloud import OpenAICompatibleProvider
from arqen.tools.base import Tool
from arqen.tools.registry import ToolRegistry
from arqen.tools.schema import build_tool_schemas


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


def test_schema_describes_tools_for_the_model() -> None:
    schemas = build_tool_schemas(_registry())
    assert len(schemas) == 1
    function = schemas[0]["function"]
    assert function["name"] == "echo"
    assert function["parameters"]["properties"] == {"text": {"type": "string"}}
    assert function["parameters"]["required"] == ["text"]


def test_streamed_tool_call_fragments_are_reassembled() -> None:
    calls: dict[int, dict] = {}
    for fragment in [
        {"index": 0, "id": "call_1", "function": {"name": "ec"}},
        {"index": 0, "function": {"name": "ho", "arguments": '{"te'}},
        {"index": 0, "function": {"arguments": 'xt": "hej"}'}},
    ]:
        OpenAICompatibleProvider._merge_call(calls, fragment)
    assert calls[0]["id"] == "call_1"
    assert calls[0]["function"]["name"] == "echo"
    assert calls[0]["function"]["arguments"] == '{"text": "hej"}'


def test_tool_result_carries_the_call_id_back() -> None:
    provider = OpenAICompatibleProvider("https://example.invalid", "m", 1.0, "k", "test")
    chat = provider._chat_messages([
        Message(role="assistant", content="", tool_calls=({"id": "call_1"},)),
        Message(role="tool", content="echo: hej", tool_call_id="call_1"),
    ])
    assert chat[0]["tool_calls"] == [{"id": "call_1"}]
    assert chat[1] == {"role": "tool", "tool_call_id": "call_1", "content": "echo: hej"}


def test_tool_result_without_call_id_stays_ordinary_context() -> None:
    provider = OpenAICompatibleProvider("https://example.invalid", "m", 1.0, "k", "test")
    chat = provider._chat_messages([Message(role="tool", content="from keyword fallback")])
    assert chat[0]["role"] == "user"
    assert "from keyword fallback" in chat[0]["content"]


class ToolThenAnswerProvider:
    """Asks for the tool once, then answers using its result."""

    supports_tools = True
    provider_name = "test"
    model = "test"

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, messages: list[Message], tools=None) -> ProviderResponse:
        self.calls += 1
        assert tools, "the engine must send tool schemas to a native provider"
        if self.calls == 1:
            return ProviderResponse(
                content="",
                tool_request=__import__("arqen.core.contracts", fromlist=["ToolRequest"]).ToolRequest(
                    name="echo", arguments={"text": "hej"}, call_id="call_1"
                ),
                tool_calls=({"id": "call_1", "function": {"name": "echo", "arguments": '{"text": "hej"}'}},),
            )
        return ProviderResponse(content="Verktyget svarade: echo: hej")


def test_engine_feeds_the_tool_result_back_to_the_model(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = ToolThenAnswerProvider()
    engine = ConversationEngine(provider=provider, tools=_registry())
    answer = engine.respond("kör echo med hej")
    assert provider.calls == 2, "the model must get a second turn after the tool ran"
    assert answer == "Verktyget svarade: echo: hej"
    assert any(m.role == "tool" and m.tool_call_id == "call_1" for m in engine.messages)


def test_cancelling_stops_before_the_provider_is_called(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = ToolThenAnswerProvider()
    engine = ConversationEngine(provider=provider, tools=_registry(), should_cancel=lambda: True)
    assert engine.respond("kör echo med hej") == "Avbrutet."
    assert provider.calls == 0


def test_leading_path_stops_at_the_file_extension() -> None:
    assert _leading_path("foo.md och implementera den") == "foo.md"
    assert _leading_path("Arqen Desktop Voice.png och beskriv den") == "Arqen Desktop Voice.png"
    assert _leading_path("anteckningar.txt") == "anteckningar.txt"
    assert _leading_path("en fil utan ändelse") == "en fil utan ändelse"
