"""The chat's own tool selection, chosen as "Arqen (chatten)" on the Connections view."""

import json
import os

import pytest

from arqen.config import paths
from arqen.core import chat_tools
from arqen.core.contracts import ProviderResponse, ToolRequest
from arqen.core.engine import ConversationEngine
from arqen.tools.builtins import create_builtin_registry


class RecordingProvider:
    """Answers at once and remembers which tools it was offered."""

    supports_tools = True
    provider_name = "test"
    model = "test"

    def __init__(self, request: ToolRequest | None = None) -> None:
        self.offered: list[str] = []
        self.request = request

    def respond(self, messages, tools=None) -> ProviderResponse:
        if tools is not None:
            self.offered = [schema["function"]["name"] for schema in tools]
        if self.request is not None and tools is not None:
            request, self.request = self.request, None
            return ProviderResponse(content="", tool_request=request, tool_calls=(
                {"id": "c1", "function": {"name": request.name, "arguments": json.dumps(request.arguments)}},
            ))
        return ProviderResponse(content="klart")


def _chat_engine(provider) -> ConversationEngine:
    engine = ConversationEngine(provider=provider, tools=create_builtin_registry())
    chat_tools.apply_chat_tool_limits(engine)
    return engine


def test_the_selection_is_stored_beside_the_rest_of_the_config():
    config = paths.config_dir() / "arqen.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"provider": {"name": "openrouter"}, "chat": {"voice": True}}), encoding="utf-8")

    chat_tools.save_denied_tools(["read_pdf", "current_time", "read_pdf"])

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["provider"] == {"name": "openrouter"}
    assert data["chat"] == {"voice": True, "denied_tools": ["current_time", "read_pdf"]}
    assert chat_tools.load_denied_tools() == ("current_time", "read_pdf")


def test_nothing_chosen_means_every_tool():
    registry = create_builtin_registry()
    assert chat_tools.load_denied_tools() == ()
    assert len(chat_tools.chat_allowed_tools(registry)) == len(registry.describe())


def test_a_taken_away_tool_is_neither_offered_nor_run():
    chat_tools.save_denied_tools(["current_time"])
    provider = RecordingProvider(ToolRequest(name="current_time", arguments={}, call_id="c1"))
    engine = _chat_engine(provider)

    engine.respond("vad är klockan?")

    assert "current_time" not in provider.offered
    assert "system_status" in provider.offered  # the rest stays
    assert engine.gateway.execute("current_time", {}).output == "Tool denied by policy: current_time"


def test_task_engines_do_not_inherit_the_chat_selection():
    chat_tools.save_denied_tools(["current_time"])
    provider = RecordingProvider()
    ConversationEngine(provider=provider, tools=create_builtin_registry()).respond("vad är klockan?")
    assert "current_time" in provider.offered


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_the_connections_view_can_give_and_take_the_chats_tools():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from arqen.ui.window import ArqenWindow

    app = QApplication.instance() or QApplication([])
    engine = _chat_engine(RecordingProvider())
    window = ArqenWindow(engine, provider_label="test")
    window._refresh_connections_view()
    assert window.connections_agent.itemText(0) == "Arqen (chatten)"
    window.connections_agent.setCurrentIndex(0)

    window._set_connector_access("builtin:documents", False)
    assert {"read_pdf", "read_docx", "read_xlsx"} <= set(chat_tools.load_denied_tools())
    assert not engine.gateway.permits("read_pdf")  # the open chat follows at once

    window._set_connector_access("builtin:documents", True)
    assert chat_tools.load_denied_tools() == ()
    assert engine.gateway.permits("read_pdf")
    window.close()
