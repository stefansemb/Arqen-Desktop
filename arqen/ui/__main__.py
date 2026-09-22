import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from arqen.config.settings import load_provider_config, load_workspace_root
from arqen.core.engine import ConversationEngine
from arqen.providers.factory import create_provider
from arqen.tools.builtins import create_builtin_registry
from arqen.ui.window import ArqenWindow


def main() -> None:
    load_workspace_root()
    config = load_provider_config()
    engine = ConversationEngine(
        provider=create_provider(config),
        tools=create_builtin_registry(),
    )
    app = QApplication(sys.argv)
    window = ArqenWindow(engine, provider_label=config.name, profile_name=config.profile_name)
    window.show()
    def center_window() -> None:
        screen = window.screen() or app.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            frame = window.frameGeometry()
            x = area.center().x() - frame.width() // 2
            y = area.center().y() - frame.height() // 2
            x = max(area.left(), min(x, area.right() - frame.width() + 1))
            y = max(area.top(), min(y, area.bottom() - frame.height() + 1))
            window.move(x, y)
    QTimer.singleShot(250, center_window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
