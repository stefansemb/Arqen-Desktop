"""Where a connection's credentials and settings are kept.

Credentials go in ``config/arqen-secrets.json`` under ``"connectors"``, which is
never committed.  Non-secret settings (paused, notify) go in
``config/arqen.json`` under ``"connectors"``.  Both files are shared with the
rest of Arqen, so every write keeps the keys it does not own.
"""

from __future__ import annotations

import json
from pathlib import Path

from arqen.config import paths


def _path(name: str) -> Path:
    # Looked up on each call so tests can point it at their own directory.
    return paths.config_dir() / name


def _read(name: str) -> dict:
    path = _path(name)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _update(name: str, connector_id: str, value: dict | None) -> None:
    data = _read(name)
    section = data.get("connectors") if isinstance(data.get("connectors"), dict) else {}
    if value is None:
        section.pop(connector_id, None)
    else:
        section[connector_id] = value
    data["connectors"] = section
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_credentials(connector_id: str) -> dict[str, str]:
    section = _read("arqen-secrets.json").get("connectors", {})
    values = section.get(connector_id, {}) if isinstance(section, dict) else {}
    return {str(key): str(value) for key, value in values.items()} if isinstance(values, dict) else {}


def save_credentials(connector_id: str, values: dict[str, str]) -> None:
    _update("arqen-secrets.json", connector_id, {key: value.strip() for key, value in values.items()})


def forget_credentials(connector_id: str) -> None:
    """Disconnect: the credentials are deleted, the settings are kept."""
    _update("arqen-secrets.json", connector_id, None)


def load_settings(connector_id: str) -> dict:
    section = _read("arqen.json").get("connectors", {})
    values = section.get(connector_id, {}) if isinstance(section, dict) else {}
    return dict(values) if isinstance(values, dict) else {}


def save_settings(connector_id: str, **changes) -> None:
    _update("arqen.json", connector_id, {**load_settings(connector_id), **changes})


def secret_values() -> list[str]:
    """Every stored key, connections and model providers alike, for scrubbing tool output."""
    from arqen.config.secrets import secret_values as every_secret

    return every_secret()
