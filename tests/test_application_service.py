from pathlib import Path

import pytest

from arqen.application.service import ArqenApplication
from arqen.core.engine import ConversationEngine
from arqen.core.session_store import SessionStore
from arqen.providers.demo import DemoProvider


def make_application(tmp_path: Path) -> ArqenApplication:
    store = SessionStore(tmp_path / "sessions")
    return ArqenApplication(lambda: ConversationEngine(DemoProvider()), store)


def test_application_creates_lists_and_sends_messages(tmp_path: Path) -> None:
    app = make_application(tmp_path)
    session = app.create_session("Mobiltest")

    result = app.send_message(session.session_id, "Hej Arqen")

    assert result.session_id == session.session_id
    assert result.assistant_message == "Jag tog emot: Hej Arqen"
    assert app.get_session(session.session_id).messages[-1].content == result.assistant_message
    assert app.list_sessions()[0].session_id == session.session_id


def test_application_renames_and_deletes_session(tmp_path: Path) -> None:
    app = make_application(tmp_path)
    session = app.create_session()

    renamed = app.rename_session(session.session_id, "Mobiltest")

    assert renamed.title == "Mobiltest"
    app.delete_session(session.session_id)
    assert app.list_sessions() == []


def test_application_rejects_empty_messages_and_titles(tmp_path: Path) -> None:
    app = make_application(tmp_path)
    session = app.create_session()

    with pytest.raises(ValueError):
        app.send_message(session.session_id, "  ")
    with pytest.raises(ValueError):
        app.rename_session(session.session_id, "  ")
