from .core.engine import ConversationEngine
from .config.settings import load_provider_config
from .providers.factory import create_provider
from .tools.builtins import create_builtin_registry


def main() -> None:
    try:
        config = load_provider_config()
        provider = create_provider(config)
    except ValueError as exc:
        print(f"Konfigurationsfel: {exc}")
        return
    engine = ConversationEngine(
        provider=provider,
        tools=create_builtin_registry(),
    )
    print(f"Provider: {config.name} ({config.model})")
    print("Arqen Desktop demo. Skriv 'quit' för att avsluta.")
    while True:
        prompt = input("Du: ").strip()
        if prompt.lower() in {"quit", "exit", "avsluta"}:
            break
        if prompt:
            try:
                print(f"Arqen: {engine.respond(prompt)}")
            except RuntimeError as exc:
                print(f"Arqen kunde inte svara: {exc}")


if __name__ == "__main__":
    main()
