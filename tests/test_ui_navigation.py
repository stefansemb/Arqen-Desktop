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
def test_chat_session_bar_loads_every_chat():
    """The session bar once read from a deleted list widget and crashed on click."""
    import gc

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    engine = ConversationEngine(provider=create_provider(config), tools=create_builtin_registry())
    window = ArqenWindow(engine, provider_label=config.name, profile_name=config.profile_name)
    engine.new_session("first")
    engine.session_store.save(engine.session)
    engine.new_session("second")
    engine.session_store.save(engine.session)
    gc.collect()
    window.refresh_sessions()
    selector = window.chat_session_selector
    assert selector.count() >= 2
    for index in range(selector.count()):
        window._load_selected_chat_from_bar(index)
        assert engine.session.session_id == selector.itemData(index)
    window.close()
