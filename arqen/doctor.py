import json
from urllib.error import URLError
from urllib.request import urlopen

from arqen.config.settings import load_provider_config


def check_local_provider(base_url: str) -> tuple[bool, str]:
    try:
        with urlopen(f"{base_url.rstrip('/')}/models", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [item.get("id", "unknown") for item in payload.get("data", [])]
        model_text = ", ".join(models) if models else "inga modeller rapporterade"
        return True, f"Provider svarar. Modeller: {model_text}"
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return False, f"Provider svarar inte: {exc}"


def main() -> None:
    config = load_provider_config()
    print(f"Provider: {config.name}")
    if config.name != "local":
        print("Diagnostik för lokal provider hoppas över.")
        return
    ok, message = check_local_provider(config.base_url)
    print(message)
    if not ok:
        print(f"Förväntad modell: {config.model}")


if __name__ == "__main__":
    main()

