import sys
from pathlib import Path

import pytest

from arqen.connectors import all_connectors, store
from arqen.connectors import mcp
from arqen.connectors.http import ServiceError
from arqen.tools.builtins import create_builtin_registry
from arqen.tools.executor import ToolExecutor
from arqen.tools.gateway import ToolGateway
from arqen.tools.schema import build_tool_schemas
from fake_mcp_server import serve_http

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))


def _stdio_server() -> dict:
    return {"id": "fake", "name": "Fake", "transport": "stdio", "command": sys.executable, "args": f'"{FAKE}"'}


def test_stdio_server_lists_and_calls_tools():
    server = _stdio_server()
    specs = mcp.fetch_tools(server)
    assert [(spec.name, spec.read_only) for spec in specs] == [("echo", True), ("create.note", False)]


@pytest.mark.parametrize("use_sse", [False, True])
def test_http_server_with_json_or_event_stream(use_sse):
    http_server, seen = serve_http(use_sse, token="s3cret-token")
    try:
        server = {"id": "web", "name": "Web", "transport": "http", "url": f"http://127.0.0.1:{http_server.server_port}/mcp"}
        specs = mcp.fetch_tools(server, "s3cret-token")
        assert [spec.name for spec in specs] == ["echo", "create.note"]
        assert seen and all(value == "Bearer s3cret-token" for value in seen)
        with pytest.raises(ServiceError):
            mcp.fetch_tools(server, "wrong")
    finally:
        http_server.shutdown()


def test_plain_http_is_refused_for_other_computers():
    with pytest.raises(ServiceError):
        mcp.fetch_tools({"id": "x", "name": "X", "transport": "http", "url": "http://example.com/mcp"})


def test_saved_servers_become_tools_that_ask_unless_read_only():
    server = _stdio_server()
    server["tools"] = [spec.to_json() for spec in mcp.fetch_tools(server)]
    mcp.save_servers([server])
    registry = create_builtin_registry()

    echo, note = registry.get("mcp_fake_echo"), registry.get("mcp_fake_create_note")
    assert echo is not None and note is not None
    assert not echo.requires_confirmation and note.requires_confirmation
    schema = next(item for item in build_tool_schemas(registry) if item["function"]["name"] == "mcp_fake_echo")
    assert schema["function"]["parameters"]["required"] == ["text"]

    gateway = ToolGateway(ToolExecutor(registry))
    assert gateway.execute("mcp_fake_echo", {"text": "hej"}).output == "echo: hej"
    assert gateway.execute("mcp_fake_create_note", {"title": "t"}).confirmation_required
    assert not gateway.execute("mcp_fake_echo", {}).ok  # required argument missing

    card = next(item for item in all_connectors(registry) if item.id == "mcp:fake")
    assert set(card.tools) == {"mcp_fake_echo", "mcp_fake_create_note"}
    store.save_settings("mcp:fake", paused=True)
    assert "mcp_fake_echo" not in {item["function"]["name"] for item in build_tool_schemas(registry)}


def test_server_errors_reach_the_model_as_failures():
    server = _stdio_server()
    server["tools"] = [spec.to_json() for spec in mcp.fetch_tools(server)]
    mcp.save_servers([server])
    executor = ToolExecutor(create_builtin_registry())
    executor.execute("mcp_fake_create_note", {"title": "t"})
    result = executor.confirm_pending(True)
    assert not result.ok and "not allowed" in result.output


def test_sync_replaces_old_server_tools():
    registry = create_builtin_registry()
    server = _stdio_server()
    server["tools"] = [spec.to_json() for spec in mcp.fetch_tools(server)]
    mcp.save_servers([server])
    mcp.sync_mcp_tools(registry)
    assert registry.get("mcp_fake_echo") is not None
    mcp.save_servers([])
    mcp.sync_mcp_tools(registry)
    assert registry.get("mcp_fake_echo") is None


def test_tool_names_fit_what_providers_accept():
    name = mcp.tool_name({"id": "zapier"}, "gmail: send.email " + "x" * 80)
    assert len(name) <= 64 and all(char.isalnum() or char in "_-" for char in name)
