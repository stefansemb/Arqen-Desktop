"""The Tools catalogue: sections that fold open and remember it."""

import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
from PyQt6.QtWidgets import QApplication, QFrame

import arqen.ui.window as window_module
from arqen.core.contracts import ProviderResponse
from arqen.core.engine import ConversationEngine
from arqen.tools.builtins import create_builtin_registry


class QuietProvider:
    supports_tools = True
    provider_name = "test"
    model = "test"

    def respond(self, messages, tools=None):
        return ProviderResponse(content="ok")


@pytest.fixture
def window(monkeypatch, tmp_path):
    # The open sections are a user setting; a test must not change the real one.
    monkeypatch.setattr(window_module, "QSettings",
                        lambda *args: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    app = QApplication.instance() or QApplication([])
    engine = ConversationEngine(provider=QuietProvider(), tools=create_builtin_registry())
    created = []

    def make():
        created.append(window_module.ArqenWindow(engine, provider_label="test"))
        created[-1]._refresh_tools_view()
        return created[-1]

    yield make
    for item in created:
        item.close()
    app.processEvents()


def _shown(window) -> tuple[int, int]:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    host = window.tools_catalog_host
    headers = host.findChildren(window_module._SectionHeader)
    cards = [frame for frame in host.findChildren(QFrame) if frame.objectName() == "toolCard"]
    return len(headers), len(cards)


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_sections_start_folded_and_open_on_click(window):
    view = window()
    sections, cards = _shown(view)
    assert sections >= 8 and cards == 0
    view._toggle_tool_section("Webb")
    assert _shown(view)[1] == 6
    view._toggle_tool_section("Webb")
    assert _shown(view)[1] == 0


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_a_search_opens_the_sections_it_matches(window):
    view = window()
    view.tools_search.setText("pdf")
    assert _shown(view) == (1, 1)
    view._toggle_tool_section("Dokument")  # can still be folded by hand
    assert _shown(view) == (1, 0)
    view.tools_search.setText("")
    assert _shown(view)[1] == 0  # back to the sections the user had open


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable")
def test_show_all_and_the_open_sections_are_remembered(window):
    view = window()
    view._toggle_all_tool_sections()
    assert _shown(view)[1] == len(create_builtin_registry().describe())
    assert view.tools_expand_all.text() == "DÖLJ ALLA"
    view._toggle_all_tool_sections()
    view._toggle_tool_section("System")
    assert window()._tool_sections_open == {"System"}
