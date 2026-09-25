"""GitHub, Discord and Telegram connections, without touching the network."""

import json

import pytest

import arqen.connectors.http as http
from arqen.connectors import all_connectors
from arqen.connectors import store
from arqen.connectors.external import connector_by_id
from arqen.connectors.messaging import DISCORD, TELEGRAM
from arqen.tools.builtins import create_builtin_registry
from arqen.tools.executor import ToolExecutor
from arqen.tools.gateway import ToolGateway
from arqen.tools.schema import build_relevant_tool_schemas, build_tool_schemas


class FakeResponse:
    def __init__(self, payload) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def web(monkeypatch):
    """Record requests and answer each from a script keyed by URL fragment."""
    calls: list[tuple[str, str, dict | None, dict]] = []
    answers: dict[str, object] = {}

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        calls.append((request.get_method(), request.full_url, body, dict(request.header_items())))
        for fragment, payload in answers.items():
            if fragment in request.full_url:
                return FakeResponse(payload)
        return FakeResponse({})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    return calls, answers


def test_connection_tools_are_hidden_until_connected():
    registry = create_builtin_registry()
    offered = {schema["function"]["name"] for schema in build_tool_schemas(registry)}
    assert "github_list_repos" not in offered
    store.save_credentials("github", {"token": "ghp_testtoken123"})
    offered = {schema["function"]["name"] for schema in build_tool_schemas(registry)}
    assert "github_list_repos" in offered
    store.save_settings("github", paused=True)
    assert "github_list_repos" not in {s["function"]["name"] for s in build_relevant_tool_schemas(registry, "github repo")}


def test_a_disconnected_tool_explains_itself():
    result = ToolExecutor(create_builtin_registry()).execute("github_list_repos", {})
    assert not result.ok and "Anslutningar" in result.output


def test_github_tools_send_the_token_but_never_return_it(web):
    calls, answers = web
    answers["/user/repos"] = [{"full_name": "stefan/arqen", "private": True, "description": "token ghp_testtoken123"}]
    store.save_credentials("github", {"token": "ghp_testtoken123"})
    gateway = ToolGateway(ToolExecutor(create_builtin_registry()))

    result = gateway.execute("github_list_repos", {})

    method, url, _, headers = calls[0]
    assert (method, url) == ("GET", "https://api.github.com/user/repos?sort=updated&per_page=30")
    assert headers["Authorization"] == "Bearer ghp_testtoken123"
    assert "stefan/arqen (private)" in result.output
    assert "ghp_testtoken123" not in result.output  # scrubbed by the gateway
    audit = gateway.audit_path.read_text(encoding="utf-8")
    assert "ghp_testtoken123" not in audit


def test_creating_an_issue_waits_for_approval_then_posts(web):
    calls, answers = web
    answers["/issues"] = {"number": 7, "html_url": "https://github.com/stefan/arqen/issues/7"}
    store.save_credentials("github", {"token": "ghp_testtoken123"})
    executor = ToolExecutor(create_builtin_registry())

    pending = executor.execute("github_create_issue", {"repo": "stefan/arqen", "title": "Bugg", "body": "text"})
    assert pending.confirmation_required and calls == []
    done = executor.confirm_pending(True)
    assert done.ok and "#7" in done.output
    assert calls[0][:3] == ("POST", "https://api.github.com/repos/stefan/arqen/issues", {"title": "Bugg", "body": "text"})


def test_issue_numbers_given_as_text_are_accepted(web):
    _, answers = web
    answers["/issues/12"] = {"number": 12, "title": "T", "state": "open", "labels": [], "body": "b"}
    store.save_credentials("github", {"token": "ghp_testtoken123"})
    result = ToolExecutor(create_builtin_registry()).execute("github_read_issue", {"repo": "stefan/arqen", "number": "#12"})
    assert result.ok and result.output.startswith("#12 T")


def test_discord_rejects_anything_but_a_webhook_address(web):
    calls, _ = web
    with pytest.raises(http.ServiceError):
        DISCORD.test({"webhook_url": "https://example.com/steal"})
    assert calls == []


def test_discord_and_telegram_send(web):
    calls, answers = web
    hook = "https://discord.com/api/webhooks/123/abc-DEF"
    DISCORD.notify({"webhook_url": hook}, "hej")
    answers["getMe"] = {"result": {"username": "arqen_bot"}}
    assert TELEGRAM.test({"bot_token": "123:ABCDEF", "chat_id": "42"}) == "@arqen_bot"
    TELEGRAM.notify({"bot_token": "123:ABCDEF", "chat_id": "42"}, "hej")
    assert calls[0][:3] == ("POST", hook, {"content": "hej"})
    assert calls[-1][:3] == ("POST", "https://api.telegram.org/bot123:ABCDEF/sendMessage", {"chat_id": "42", "text": "hej"})


def test_external_connectors_have_their_own_cards():
    connectors = {item.id: item for item in all_connectors(create_builtin_registry())}
    assert {"github", "discord", "telegram"} <= set(connectors)
    builtin_tools = {tool for item in connectors.values() if item.builtin for tool in item.tools}
    assert not builtin_tools & set(connectors["github"].tools)
    assert connector_by_id("github").is_connected() is False


def test_credentials_are_kept_apart_from_other_secrets():
    secrets = store._path("arqen-secrets.json")
    secrets.parent.mkdir(parents=True, exist_ok=True)
    secrets.write_text(json.dumps({"providers": {"openai": "sk-keep"}}), encoding="utf-8")
    store.save_credentials("github", {"token": "t1"})
    store.forget_credentials("github")
    assert json.loads(secrets.read_text(encoding="utf-8")) == {"providers": {"openai": "sk-keep"}, "connectors": {}}


def test_finished_tasks_are_announced_once_and_only_when_asked(web):
    import os
    import time

    if os.name != "nt" and not os.environ.get("DISPLAY"):
        pytest.skip("Qt display is unavailable")
    from PyQt6.QtWidgets import QApplication

    from arqen.config.settings import load_provider_config
    from arqen.core.engine import ConversationEngine
    from arqen.mission import Task
    from arqen.providers.factory import create_provider
    from arqen.ui.window import ArqenWindow

    calls, _ = web
    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    window = ArqenWindow(ConversationEngine(provider=create_provider(config), tools=create_builtin_registry()),
                         provider_label=config.name, profile_name=config.profile_name)
    window.mission_activity_timer.stop()  # drive the checks by hand
    hook = "https://discord.com/api/webhooks/123/abc-DEF"
    store.save_credentials("discord", {"webhook_url": hook})
    task = Task.create("Research", "gör research")
    window.mission_store.save_task(task)

    window._notify_task_changes()  # first look only remembers
    window.mission_store.update_task(task.id, "completed", result="ok")
    window._notify_task_changes()
    time.sleep(0.2)
    assert calls == []  # notifications are off until the user turns them on

    store.save_settings("discord", notify=True)
    other = Task.create("Skriv manus", "skriv")
    window.mission_store.save_task(other)
    window._notify_task_changes()
    window.mission_store.update_task(other.id, "failed", error="timeout")
    window._notify_task_changes()
    window._notify_task_changes()  # no second message for the same change
    deadline = time.monotonic() + 3
    while not calls and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)
    assert len(calls) == 1
    method, url, body, _ = calls[0]
    assert (method, url) == ("POST", hook)
    assert "Skriv manus" in body["content"] and "timeout" in body["content"]
    window.close()
