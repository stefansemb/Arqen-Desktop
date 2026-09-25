from pathlib import Path

from arqen.config.settings import load_provider_config, save_provider_config
from arqen.providers.config import ProviderConfig


def _saved(tmp_path: Path, **fallback) -> ProviderConfig:
    config_path = tmp_path / "arqen.json"
    save_provider_config(ProviderConfig(name="openrouter", model="m", **fallback), config_path)
    return load_provider_config(config_path)


def test_fallback_settings_can_be_changed_and_switched_off(tmp_path) -> None:
    """The saved fallback block used to freeze at whatever was written first.

    Enabling it once worked; changing the provider, changing the timeout or
    switching it off again all went nowhere, because the save kept the old
    block instead of the one it had just been handed.
    """
    first = _saved(tmp_path, fallback_enabled=True, fallback_provider="local", fallback_timeout=30.0)
    assert (first.fallback_enabled, first.fallback_provider, first.fallback_timeout) == (True, "local", 30.0)

    changed = _saved(tmp_path, fallback_enabled=True, fallback_provider="gemini", fallback_timeout=90.0)
    assert (changed.fallback_enabled, changed.fallback_provider, changed.fallback_timeout) == (True, "gemini", 90.0)

    switched_off = _saved(tmp_path, fallback_enabled=False, fallback_provider="", fallback_timeout=10.0)
    assert switched_off.fallback_enabled is False


def test_saving_a_provider_keeps_everything_else_in_both_files(tmp_path):
    """Save used to rewrite both files from scratch, deleting theme, mission and connector keys."""
    import json

    config_path = tmp_path / "arqen.json"
    secrets_path = tmp_path / "arqen-secrets.json"
    config_path.write_text(json.dumps({"theme": {"voice": {"speaking": "#ff8800"}}, "connectors": {"github": {"paused": True}}}), encoding="utf-8")
    secrets_path.write_text(json.dumps({"providers": {"openai": "k1"}, "connectors": {"github": {"token": "t"}}}), encoding="utf-8")

    save_provider_config(ProviderConfig(name="openrouter", model="m", api_key="k2"), config_path)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
    assert config["theme"] == {"voice": {"speaking": "#ff8800"}}
    assert config["connectors"] == {"github": {"paused": True}}
    assert secrets["connectors"] == {"github": {"token": "t"}}
    assert secrets["providers"] == {"openai": "k1", "openrouter": "k2"}
