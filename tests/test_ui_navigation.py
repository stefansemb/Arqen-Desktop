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
