import argparse
import os

from arqen.application.service import ArqenApplication
from arqen.config.settings import load_provider_config
from arqen.core.engine import ConversationEngine
from arqen.providers.factory import create_provider
from arqen.tools.builtins import create_builtin_registry
from arqen.api.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Starta Arqens lokala API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("ARQEN_API_TOKEN", ""))
    args = parser.parse_args()

    config = load_provider_config()

    def engine_factory() -> ConversationEngine:
        return ConversationEngine(
            provider=create_provider(config),
            tools=create_builtin_registry(),
        )

    application = ArqenApplication(engine_factory)
    server = create_server(application, host=args.host, port=args.port, token=args.token)
    print(f"Arqen API kör på http://{args.host}:{server.server_port}")
    print("Tryck Ctrl+C för att stoppa.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
