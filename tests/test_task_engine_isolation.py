"""A mission task must never change or write into the engine the user chats with."""

import os

import pytest

from arqen.config import paths
from arqen.core.engine import ConversationEngine
from arqen.mission.runtime import ArqenRuntime
from arqen.providers.demo import DemoProvider
from arqen.tools.builtins import create_builtin_registry


def _engine() -> ConversationEngine:
    return ConversationEngine(provider=DemoProvider(), tools=create_builtin_registry())


def test_task_transcripts_stay_out_of_the_chat_list():
    engine = _engine()
    ArqenRuntime(lambda: engine).run("hej från en uppgift", allowed_tools=("current_time",))
    assert engine.session_store.list_sessions()  # the run is kept...
    assert engine.session_store.base_dir == paths.data_dir() / "mission-sessions"
    chats = ConversationEngine(provider=DemoProvider()).session_store.list_sessions()
    assert chats == []  # ...but not among the user's chats


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_desktop_tasks_get_their_own_engine():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from arqen.ui.window import ArqenWindow

    app = QApplication.instance() or QApplication([])
    chat_engine = _engine()
    window = ArqenWindow(chat_engine, provider_label="demo")
    tools_before = set(chat_engine.tools._tools)

    task_engine = window._new_task_engine()
    assert task_engine is not chat_engine
    # What an agent's run does to its engine: narrow the tools, force approvals.
    task_engine.tools._tools = {"current_time": task_engine.tools._tools["current_time"]}
    task_engine.executor.forced_confirmation = {"current_time"}

    assert set(chat_engine.tools._tools) == tools_before
    assert chat_engine.executor.forced_confirmation == set()
    window.close()
