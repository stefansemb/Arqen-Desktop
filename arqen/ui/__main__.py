import sys

from PyQt6.QtWidgets import QApplication

from arqen.config.settings import load_provider_config
from arqen.core.engine import ConversationEngine
from arqen.providers.factory import create_provider
from arqen.tools.builtins import create_builtin_registry
from arqen.ui.window import ArqenWindow


def main() -> None:
    config = load_provider_config()
    engine = ConversationEngine(
        provider=create_provider(config),
        tools=create_builtin_registry(),
    )
    app = QApplication(sys.argv)
    window = ArqenWindow(engine, provider_label=config.name, profile_name=config.profile_name)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
