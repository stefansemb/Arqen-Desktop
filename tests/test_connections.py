import os

import pytest

from arqen.connectors import GrantState, all_connectors, grant_state, with_connector, without_connector
from arqen.core.engine import ConversationEngine
from arqen.mission import Agent
from arqen.mission.runtime import ArqenRuntime
from arqen.providers.demo import DemoProvider
from arqen.tools.builtins import create_builtin_registry


def _connector(identifier: str):
    return next(item for item in all_connectors(create_builtin_registry()) if item.id == identifier)


def test_every_builtin_tool_is_in_exactly_one_connector():
    registry = create_builtin_registry()
    packaged = [tool for connector in all_connectors(registry) for tool in connector.tools]
    assert sorted(packaged) == sorted(entry["name"] for entry in registry.describe())


def test_granting_and_removing_a_connector():
    web = _connector("builtin:web")
    assert grant_state(web, ()) is GrantState.NONE
    tools = with_connector(web, ("current_time",))
    assert tools[0] == "current_time" and grant_state(web, tools) is GrantState.FULL
    assert grant_state(web, tools[:2]) is GrantState.PARTIAL
    assert without_connector(web, tools) == ("current_time",)


def test_an_agent_with_no_tools_gets_none_not_all():
    """An empty list used to mean "every tool", so removing the last one unlocked everything."""
    engine = ConversationEngine(provider=DemoProvider(), tools=create_builtin_registry())
    ArqenRuntime(lambda: engine).run("hej", allowed_tools=())
    assert engine.tools.describe() == []
    unlimited = ConversationEngine(provider=DemoProvider(), tools=create_builtin_registry())
    ArqenRuntime(lambda: unlimited).run("hej", allowed_tools=None)
    assert len(unlimited.tools.describe()) == len(create_builtin_registry().describe())


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_connections_view_grants_tools_to_the_chosen_agent():
    from PyQt6.QtWidgets import QApplication

    from arqen.config.settings import load_provider_config
    from arqen.providers.factory import create_provider
    from arqen.ui.window import ArqenWindow

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    window = ArqenWindow(
        ConversationEngine(provider=create_provider(config), tools=create_builtin_registry()),
        provider_label=config.name,
        profile_name=config.profile_name,
    )
    store = window.mission_store  # the test's own database, see conftest
    store.save_agent(Agent("tester", "Tester", "QA", allowed_tools=("current_time",), approval_tools=("current_time",)))
    window._refresh_connections_view()
    window.connections_agent.setCurrentIndex(window.connections_agent.findData("tester"))

    window._set_connector_access("builtin:web", True)
    assert set(_connector("builtin:web").tools) <= set(store.get_agent("tester").allowed_tools)
    # current_time plus every web tool
    assert f"{1 + len(_connector('builtin:web').tools)} av" in window.connections_summary.text()

    window._set_connector_access("builtin:system", False)  # current_time lives there
    agent = store.get_agent("tester")
    assert "current_time" not in agent.allowed_tools
    assert agent.approval_tools == ()  # rules for removed tools go with them

    # Enabling or disabling must keep the allowance intact.
    window.mission_agents.clear()
    from PyQt6.QtWidgets import QListWidgetItem
    from PyQt6.QtCore import Qt
    item = QListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, "tester")
    window.mission_agents.addItem(item)
    window.mission_agents.setCurrentItem(item)
    before = store.get_agent("tester").allowed_tools
    window._toggle_mission_agent()
    after = store.get_agent("tester")
    assert after.enabled is False and after.allowed_tools == before
    window.close()
