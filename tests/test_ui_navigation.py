import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from arqen.config.settings import load_provider_config
from arqen.core.engine import ConversationEngine
from arqen.providers.factory import create_provider
from arqen.tools.builtins import create_builtin_registry
from arqen.ui.window import ArqenWindow


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_mission_control_navigation_is_complete():
    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    window = ArqenWindow(
        ConversationEngine(provider=create_provider(config), tools=create_builtin_registry()),
        provider_label=config.name,
        profile_name=config.profile_name,
    )
    expected = {
        "Dashboard", "Chat", "Mission Control", "Tasks", "Workflows",
            "Schedules", "Agents", "Activity", "Memory", "Tools", "Content", "Settings",
    }
    assert set(window.navigation_buttons) == expected
    assert window.navigation_stack.count() == 11
    window.close()
    app.quit()


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_chat_list_opens_renames_and_deletes_chats(monkeypatch):
    """The chat picker once read from a deleted widget and crashed on click."""
    import gc

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QInputDialog, QMessageBox

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    engine = ConversationEngine(provider=create_provider(config), tools=create_builtin_registry())
    window = ArqenWindow(engine, provider_label=config.name, profile_name=config.profile_name)
    engine.new_session("first")
    engine.session_store.save(engine.session)
    engine.new_session("second\nline")
    engine.session_store.save(engine.session)
    gc.collect()
    window.refresh_sessions()
    chat_list = window.chat_list
    assert chat_list.count() >= 2
    # Multi-line titles are flattened so every row keeps one line.
    assert "second line" in [chat_list.item(row).text() for row in range(chat_list.count())]
    for row in range(chat_list.count()):
        chat_list.setCurrentRow(row)
        window.load_selected_session()
        assert engine.session.session_id == chat_list.item(row).data(Qt.ItemDataRole.UserRole)

    target = next(row for row in range(chat_list.count()) if chat_list.item(row).text() == "first")
    chat_list.setCurrentRow(target)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("renamed", True))
    window.rename_selected_session()
    titles = [chat_list.item(row).text() for row in range(chat_list.count())]
    assert "renamed" in titles and "first" not in titles

    chat_list.setCurrentRow(titles.index("renamed"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.delete_selected_session()
    assert "renamed" not in [chat_list.item(row).text() for row in range(chat_list.count())]
    window.close()


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_approval_bar_shows_and_answers_pending_decisions():
    from arqen.mission import Task

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    window = ArqenWindow(
        ConversationEngine(provider=create_provider(config), tools=create_builtin_registry()),
        provider_label=config.name,
        profile_name=config.profile_name,
    )
    assert window.approval_bar.isHidden()

    window.show_confirmation("close_program", {"target": "notepad"})
    assert not window.approval_bar.isHidden()
    assert "notepad" in window.approval_detail.text()
    window.resolve_confirmation(False)
    assert window.approval_bar.isHidden()

    task = Task.create("Skriv rapport", "skriv", agent_id=None)
    window.mission_store.save_task(task)
    window.mission_store.update_task(task.id, "running")
    window.mission_runner.request_approval(task.id, "write_workspace_file", {"path": "rapport.md"})
    window._refresh_approval_bar()
    assert "Skriv rapport" in window.approval_detail.text()

    # Rejecting must cancel the task, not leave it waiting forever.
    window._answer_first_approval(False)
    assert window.mission_store.get_task(task.id).status == "cancelled"
    assert window.approval_bar.isHidden()
    window.close()


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_choosing_a_profile_keeps_a_realistic_fallback_timeout():
    """Profiles used to write 10 s, far below a real turn (one took 58 s)."""
    from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit

    from arqen.providers.config import ProviderConfig

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    window = ArqenWindow(
        ConversationEngine(provider=create_provider(config), tools=create_builtin_registry()),
        provider_label=config.name,
        profile_name=config.profile_name,
    )
    provider, model, fallback_provider = QComboBox(), QComboBox(), QComboBox()
    for value in ("local", "openrouter", "openai", "gemini"):
        provider.addItem(value, value)
    base_url, timeout, api_key, fallback_timeout = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit("10.0")
    window.apply_provider_profile(
        "fast", provider, model, base_url, timeout, api_key, QCheckBox(), fallback_provider, fallback_timeout
    )
    assert float(fallback_timeout.text()) == ProviderConfig().fallback_timeout == 90.0
    window.close()
