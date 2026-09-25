import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from arqen.ui.window import ChatInput

pytestmark = pytest.mark.skipif(
    os.name != "nt" and not os.environ.get("DISPLAY"), reason="Qt display is unavailable"
)


_app = None


def _input() -> tuple[ChatInput, list[str]]:
    # Kept in a variable: an unreferenced QApplication is collected at once and
    # the next widget then takes the whole test process down.
    global _app
    _app = QApplication.instance() or QApplication([])
    box = ChatInput()
    box.resize(400, box.height())
    box.show()
    sent: list[str] = []
    box.returnPressed.connect(lambda: sent.append(box.text()))
    return box, sent


def test_shift_enter_starts_a_new_line_and_enter_sends():
    box, sent = _input()
    QTest.keyClicks(box, "rad ett")
    QTest.keyClick(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(box, "rad två")
    assert box.text() == "rad ett\nrad två"  # a real newline, not U+2028
    assert sent == []

    QTest.keyClick(box, Qt.Key.Key_Return)
    assert sent == ["rad ett\nrad två"]
    QTest.keyClick(box, Qt.Key.Key_Enter)  # the keypad Enter sends too
    assert len(sent) == 2
    box.close()


def test_the_box_grows_with_its_lines_up_to_a_limit():
    box, _ = _input()
    one_line = box.height()
    box.setText("1\n2\n3")
    three_lines = box.height()
    assert three_lines > one_line
    box.setText("\n".join(str(n) for n in range(20)))
    capped = box.height()
    box.setText("\n".join(str(n) for n in range(40)))
    assert box.height() == capped  # stops growing and scrolls instead
    box.clear()
    assert box.height() == one_line
    box.close()
