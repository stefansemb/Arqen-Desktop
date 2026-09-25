from arqen.core.contracts import Message, ProviderResponse
from arqen.core.memory_store import MemoryStore
from arqen.core.reflection import gather_sources, parse_lessons, reflect
from arqen.core.session_store import SessionStore
from arqen.mission import MissionStore, Task
from arqen.mission.contracts import Approval


class ScriptedProvider:
    """Answers with a fixed reply and remembers what it was asked."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.asked: list[list[Message]] = []

    def respond(self, messages):
        self.asked.append(messages)
        return ProviderResponse(content=self.reply)


class SilentProvider:
    def respond(self, messages):
        raise AssertionError("no model call is needed when there is nothing to read")


def _chat(store: SessionStore, title: str, *said: str) -> None:
    session = store.create(title)
    for text in said:
        session.messages.append(Message(role="user", content=text))
        session.messages.append(Message(role="assistant", content="svar som inte ska läsas"))
    store.save(session)


def test_parse_lessons_tolerates_fences_prose_and_objects():
    reply = 'Här är lärdomarna:\n```json\n["Användaren vill ha svenska.", {"lesson": "Scout misslyckas ofta med Reddit."}]\n```'
    assert parse_lessons(reply) == ["Användaren vill ha svenska.", "Scout misslyckas ofta med Reddit."]
    assert parse_lessons("inget JSON här") == []
    assert parse_lessons("[trasig json") == []


def test_parse_lessons_drops_secrets_duplicates_and_extras():
    lessons = [f"Lärdom {n}" for n in range(8)] + ["lärdom 1", "Lösenordet är hunter2"]
    import json
    parsed = parse_lessons(json.dumps(lessons))
    assert parsed == [f"Lärdom {n}" for n in range(5)]
    assert parse_lessons('["Lösenordet är hunter2"]') == []


def test_sources_cover_tasks_and_only_the_users_words(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    memory.retain("Användaren bor i Göteborg")
    missions = MissionStore(tmp_path / "mission.sqlite3")
    failed = Task.create("Hämta Reddit-trådar", "hämta")
    missions.save_task(failed)
    missions.update_task(failed.id, "failed", error="403 Forbidden")
    missions.save_approval(Approval("a1", failed.id, "write_workspace_file", {}, "rejected"))
    sessions = SessionStore(tmp_path / "sessions")
    _chat(sessions, "Väder", "vad blir vädret i Göteborg?")

    sources = gather_sources(memory, missions, sessions)
    assert sources.memories == ["Användaren bor i Göteborg"]
    [task] = sources.tasks
    assert "403 Forbidden" in task and "rejected write_workspace_file" in task
    [chat] = sources.chats
    assert "vad blir vädret" in chat and "svar som inte ska läsas" not in chat


def test_reflect_stores_new_lessons_as_suggestions(tmp_path):
    memory = MemoryStore(tmp_path / "memory.json")
    memory.retain("Användaren vill ha svenska.")
    sessions = SessionStore(tmp_path / "sessions")
    _chat(sessions, "Språk", "skriv på svenska tack")
    provider = ScriptedProvider('["Användaren vill ha svenska.", "Användaren föredrar korta svar."]')

    result = reflect(provider, memory, session_store=sessions)

    assert result.added == ["Användaren föredrar korta svar."]
    assert result.skipped == 1  # already in memory
    new = next(r for r in memory.records() if r.content == "Användaren föredrar korta svar.")
    assert (new.status, new.source) == ("proposed", "reflect")
    assert [r.content for r in memory.recall()] == ["Användaren vill ha svenska."]  # not trusted yet


def test_reflect_skips_the_model_when_there_is_nothing_to_read(tmp_path):
    result = reflect(SilentProvider(), MemoryStore(tmp_path / "memory.json"), session_store=SessionStore(tmp_path / "s"))
    assert not result.had_sources and result.added == []


def test_reflect_button_adds_suggestions_in_the_memory_view(monkeypatch):
    import os
    import time

    import pytest

    if os.name != "nt" and not os.environ.get("DISPLAY"):
        pytest.skip("Qt display is unavailable")
    from PyQt6.QtWidgets import QApplication

    import arqen.ui.window as window_module
    from arqen.config.settings import load_provider_config
    from arqen.core.engine import ConversationEngine
    from arqen.providers.factory import create_provider
    from arqen.tools.builtins import create_builtin_registry

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    engine = ConversationEngine(provider=create_provider(config), tools=create_builtin_registry())
    window = window_module.ArqenWindow(engine, provider_label=config.name, profile_name=config.profile_name)
    _chat(engine.session_store, "Språk", "svara kort och på svenska")
    monkeypatch.setattr(window_module, "create_provider", lambda _config: ScriptedProvider('["Användaren vill ha korta svar."]'))

    window._start_reflection()
    deadline = time.monotonic() + 5
    while getattr(window, "reflection_thread", None) is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert window.memory_reflect_button.isEnabled()
    assert "ett nytt förslag" in window.memory_reflect_status.text()
    assert [(r.content, r.status) for r in MemoryStore().records()] == [("Användaren vill ha korta svar.", "proposed")]
    assert window.navigation_buttons["Memory"].text().endswith("· 1")
    window.close()
