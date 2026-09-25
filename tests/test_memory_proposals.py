import os

import pytest

from arqen.core.memory_store import MemoryStore
from arqen.tools.builtins import create_builtin_registry
from arqen.tools.executor import ToolExecutor
from arqen.tools.memory_tools import ProposeMemoryTool
from arqen.tools.registry import ToolRegistry
from arqen.tools.schema import build_relevant_tool_schemas


def _executor(store: MemoryStore) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(ProposeMemoryTool(store))
    return ToolExecutor(registry)


def test_a_proposal_waits_for_approval(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    result = _executor(store).execute("propose_memory", {"fact": "Min hund heter Bosse"})
    assert result.ok and not result.confirmation_required
    [record] = store.records()
    assert (record.content, record.status, record.source) == ("Min hund heter Bosse", "proposed", "arqen")
    assert store.recall() == []  # not presented to the model until approved


def test_secrets_are_never_proposed(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    executor = _executor(store)
    for fact in ("Mitt lösenord är hemligt123", "API-nyckeln är sk-abcdefghijklmnopqrstu"):
        assert not executor.execute("propose_memory", {"fact": fact}).ok
    # Ordinary words that merely contain "token" are fine.
    assert executor.execute("propose_memory", {"fact": "Jag vill se tokens i statistiken"}).ok
    assert [record.content for record in store.records()] == ["Jag vill se tokens i statistiken"]


def test_known_facts_are_not_proposed_twice(tmp_path):
    store = MemoryStore(tmp_path / "memory.json")
    store.retain("Jag bor i Göteborg")
    output = _executor(store).execute("propose_memory", {"fact": "jag bor i göteborg"}).output
    assert "Already in memory" in output
    assert len(store.records()) == 1


def test_proposal_tool_is_offered_even_without_matching_words():
    registry = create_builtin_registry()
    names = [schema["function"]["name"] for schema in build_relevant_tool_schemas(registry, "läs filen rapport.pdf")]
    assert "propose_memory" in names
    assert len(names) < len(registry.describe())  # the selection still narrows


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_memory_view_reviews_suggestions():
    from PyQt6.QtWidgets import QApplication

    from arqen.config.settings import load_provider_config
    from arqen.core.engine import ConversationEngine
    from arqen.providers.factory import create_provider
    from arqen.ui.window import ArqenWindow

    app = QApplication.instance() or QApplication([])
    config = load_provider_config()
    window = ArqenWindow(
        ConversationEngine(provider=create_provider(config), tools=create_builtin_registry()),
        provider_label=config.name,
        profile_name=config.profile_name,
    )
    store = MemoryStore()  # the test's own data directory, see conftest
    store.retain("Min hund heter Bosse", status="proposed", source="arqen")
    store.retain("Jag gillar kaffe", status="proposed", source="arqen")
    window._refresh_memory_view()
    assert window.navigation_buttons["Memory"].text().endswith("· 2")
    assert not window.memory_proposals_host.isHidden()

    window._approve_memory("Min hund heter Bosse")
    window._reject_memory("Jag gillar kaffe")
    assert [(r.content, r.status) for r in MemoryStore().records()] == [("Min hund heter Bosse", "approved")]
    assert "·" not in window.navigation_buttons["Memory"].text()
    assert window.memory_proposals_host.isHidden()

    window.memory_view_list.setCurrentRow(0)
    window._toggle_memory_obsolete()
    assert MemoryStore().records()[0].status == "obsolete"
    window.close()
