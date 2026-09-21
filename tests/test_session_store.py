from arqen.core.contracts import Message
from arqen.core.session_store import SessionStore


def test_session_can_be_saved_and_loaded(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create("Testchatt")
    session.messages.append(Message(role="user", content="Hej"))
    store.save(session)

    loaded = store.load(session.session_id)
    assert loaded.title == "Testchatt"
    assert loaded.messages[0].content == "Hej"
    assert store.list_sessions()[0].session_id == session.session_id

