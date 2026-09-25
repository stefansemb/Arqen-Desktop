"""The one place Arqen reads its keys from.

Every key lives in ``config/arqen-secrets.json``: the model providers under
``"providers"``, the connections under ``"connectors"``.  Providers get their
key when they are built, since each model call has to carry it.  Tools never
read the file: a tool asks for its key while it runs (``Tool.credentials`` for
a connection, ``Tool.provider_key`` for a model provider), the tool gateway
removes every stored key from what the tool answers, and the file tools
refuse to touch the file itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from arqen.config import paths

SECRETS_FILE = "arqen-secrets.json"
# Shorter values are too likely to occur in ordinary text to be scrubbed.
_MIN_SECRET_LENGTH = 6


def secrets_path() -> Path:
    # Looked up on each call so tests can point it at their own directory.
    return paths.config_dir() / SECRETS_FILE


def read_secrets() -> dict:
    path = secrets_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def provider_key(provider_name: str) -> str:
    """The API key of a model provider such as "openrouter"."""
    secrets = read_secrets()
    providers = secrets.get("providers") if isinstance(secrets.get("providers"), dict) else {}
    return str(providers.get(provider_name, secrets.get("api_key", "")) or "")


def secret_values() -> list[str]:
    """Every stored key, longest first, for scrubbing text before the model sees it."""
    found: set[str] = set()

    def collect(value) -> None:
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str) and len(value.strip()) >= _MIN_SECRET_LENGTH:
            found.add(value.strip())

    collect(read_secrets())
    return sorted(found, key=len, reverse=True)


def scrub(text: str) -> str:
    for secret in secret_values():
        text = text.replace(secret, "••••")
    return text


def is_secrets_file(path: Path) -> bool:
    """Whether ``path`` is the key file, or a copy of it, which no tool may read or change."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return True
    return resolved.name.casefold() == SECRETS_FILE or resolved == secrets_path().resolve()
