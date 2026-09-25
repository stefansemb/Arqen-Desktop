from arqen.core.contracts import Message, ProviderResponse, ToolRequest
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


def test_gpt_56_disables_reasoning_for_chat_completion_tools() -> None:
    provider = OpenAICompatibleProvider("https://example.invalid", "gpt-5.6", 1.0, "k", "openai")
    request = provider._request([], [{"type": "function"}], stream=False)
    import json

    assert json.loads(request.data)["reasoning_effort"] == "none"


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


class ConfirmTool(Tool):
    name = "confirm_me"
    description = "Writes something and needs approval first."
    requires_confirmation = True
    arguments_schema = {"text": str}

    def run(self, arguments):
        return f"wrote: {arguments['text']}"


class ConfirmThenAnswerProvider:
    """Asks for a gated tool, then reports on the result once approved."""

    supports_tools = True
    provider_name = "test"
    model = "test"

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, messages: list[Message], tools=None) -> ProviderResponse:
        self.calls += 1
        if self.calls == 1:
            return ProviderResponse(
                content="",
                tool_request=ToolRequest(name="confirm_me", arguments={"text": "hej"}, call_id="call_1"),
                tool_calls=({"id": "call_1", "function": {"name": "confirm_me", "arguments": '{"text": "hej"}'}},),
            )
        return ProviderResponse(content="Klart, jag skrev hej.")


def _confirm_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ConfirmTool())
    return registry


def test_approving_a_tool_hands_the_turn_back_to_the_model(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = ConfirmThenAnswerProvider()
    engine = ConversationEngine(provider=provider, tools=_confirm_registry())
    asked = engine.respond("skriv hej")
    assert "bekräftelse" in asked
    assert provider.calls == 1
    answer = engine.confirm_pending_tool(True)
    assert provider.calls == 2, "the model must continue once the user approves"
    assert answer == "Klart, jag skrev hej."
    assert engine.last_tool_output == "wrote: hej"


def test_declining_a_tool_does_not_call_the_model_again(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = ConfirmThenAnswerProvider()
    engine = ConversationEngine(provider=provider, tools=_confirm_registry())
    engine.respond("skriv hej")
    assert engine.confirm_pending_tool(False) == "Tool request cancelled"
    assert provider.calls == 1


class NeverStopsProvider:
    """Keeps asking for the tool until the engine takes the tools away."""

    supports_tools = True
    provider_name = "test"
    model = "test"

    def __init__(self) -> None:
        self.with_tools = 0
        self.without_tools = 0

    def respond(self, messages: list[Message], tools=None) -> ProviderResponse:
        if tools is None:
            self.without_tools += 1
            return ProviderResponse(content="Sammanfattningsvis: echo körde flera gånger.")
        self.with_tools += 1
        return ProviderResponse(
            content="",
            tool_request=ToolRequest(name="echo", arguments={"text": "hej"}, call_id=f"c{self.with_tools}"),
            tool_calls=({"id": f"c{self.with_tools}", "function": {"name": "echo", "arguments": '{"text": "hej"}'}},),
        )


def test_a_spent_tool_budget_still_ends_in_words(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = NeverStopsProvider()
    engine = ConversationEngine(provider=provider, tools=_registry(), max_tool_steps=3)
    answer = engine.respond("kör echo i all evighet")
    assert provider.with_tools == 3
    assert provider.without_tools == 1, "the last call must drop the tools so the model has to answer"
    assert answer == "Sammanfattningsvis: echo körde flera gånger."
    assert not answer.startswith("echo:"), "raw tool output must not be served as the answer"


def test_only_irreversible_tools_ask_for_confirmation() -> None:
    """Writing files, spending money, ending processes and posting to outside services ask."""
    from arqen.tools.builtins import create_builtin_registry

    gated = {tool["name"] for tool in create_builtin_registry().describe() if tool["requires_confirmation"]}
    assert gated == {
        "write_workspace_file",
        "delete_workspace_file",
        "move_workspace_file",
        "undo_workspace_file_change",
        "generate_image",
        "close_program",
        "github_create_issue",
        "discord_send_message",
        "telegram_send_message",
    }
