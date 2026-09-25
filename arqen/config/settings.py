import json
import re
from dataclasses import asdict
from pathlib import Path

from arqen.config.paths import APP_ROOT, config_dir, set_workspace_root
from arqen.providers.config import ProviderConfig


DEFAULT_CONFIG = ProviderConfig()


def load_api_key(provider_name: str) -> str:
    from arqen.config.secrets import provider_key

    return provider_key(provider_name)


def load_provider_config(path: Path | None = None) -> ProviderConfig:
    config_path = path or config_dir() / "arqen.json"
    if not config_path.exists():
        return DEFAULT_CONFIG
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read Arqen configuration: {exc}") from exc
    provider = data.get("provider", {})
    provider_name = str(provider.get("name", DEFAULT_CONFIG.name))
    profiles = data.get("providers", {})
    if provider_name in profiles:
        provider = {**provider, **profiles[provider_name]}
    api_key = load_api_key(str(provider.get("name", DEFAULT_CONFIG.name)))
    return ProviderConfig(
        name=provider_name,
        base_url=str(provider.get("base_url", DEFAULT_CONFIG.base_url)),
        model=re.sub(r"^\[[^\]]+\]\s*", "", str(provider.get("model", DEFAULT_CONFIG.model))),
        timeout=float(provider.get("timeout", DEFAULT_CONFIG.timeout)),
        api_key=api_key,
        fallback_enabled=bool(data.get("fallback", {}).get("enabled", False)),
        fallback_provider=str(data.get("fallback", {}).get("provider", "")),
        fallback_timeout=float(data.get("fallback", {}).get("timeout", 90.0)),
        profile_name=str(data.get("profile", "")),
    )


def load_provider_profile(provider_name: str, path: Path | None = None) -> ProviderConfig:
    """Load a saved provider profile, including its provider-specific key."""
    config_path = path or config_dir() / "arqen.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    profile = dict(data.get("providers", {}).get(provider_name, {}))
    if not profile and data.get("provider", {}).get("name") == provider_name:
        profile = dict(data.get("provider", {}))
    defaults = ProviderConfig(name=provider_name)
    return ProviderConfig(
        name=provider_name,
        base_url=str(profile.get("base_url", defaults.base_url)),
        model=re.sub(r"^\[[^\]]+\]\s*", "", str(profile.get("model", defaults.model))),
        timeout=float(profile.get("timeout", defaults.timeout)),
        api_key=load_api_key(provider_name),
    )


def save_provider_config(config: ProviderConfig, path: Path | None = None) -> None:
    config_path = path or config_dir() / "arqen.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {key: value for key, value in asdict(config).items() if key != "api_key"}
    profile["model"] = re.sub(r"^\[[^\]]+\]\s*", "", str(profile["model"]))
    # Start from what is on disk: other parts of Arqen keep their own keys in
    # these files (theme, mission, connectors, connector credentials), and
    # rewriting them from scratch here used to delete all of that on Save.
    data: dict = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    providers_profiles = data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}
    providers_profiles[config.name] = profile
    data.update({
        "provider": profile,
        "profile": config.profile_name,
        "providers": providers_profiles,
        # The fallback block is whatever was just saved.  Keeping the old
        # one froze it at its first value: it could be switched on once and
        # never changed or switched off again from the dialog.
        "fallback": {
            "enabled": config.fallback_enabled,
            "provider": config.fallback_provider,
            "timeout": config.fallback_timeout,
        },
    })
    # Saving a provider must not reset which folder Arqen works in.
    data.setdefault("workspace", "")
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    secrets_path = config_path.parent / "arqen-secrets.json"
    secrets: dict = {}
    if secrets_path.exists():
        try:
            secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            secrets = {}
    providers = secrets.get("providers", {}) if isinstance(secrets.get("providers"), dict) else {}
    providers[config.name] = config.api_key
    secrets["providers"] = providers
    secrets_path.write_text(json.dumps(secrets, indent=2) + "\n", encoding="utf-8")


def load_workspace_root(path: Path | None = None) -> Path:
    """The folder the file tools work in, or the app root until one is chosen."""
    config_path = path or config_dir() / "arqen.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return APP_ROOT
    return set_workspace_root(str(data.get("workspace", "")).strip())


def save_workspace_root(root: Path | str, path: Path | None = None) -> Path:
    """Store the chosen workspace and apply it to the running tools."""
    config_path = path or config_dir() / "arqen.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    applied = set_workspace_root(root)
    data: dict = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["workspace"] = "" if applied == APP_ROOT else str(applied)
    config_path.write_text(json.dumps(data, indent=2) + '\n', encoding="utf-8")


def load_mission_runtime_config(path: Path | None = None) -> dict:
    """Load optional Mission Control runtime settings without enabling them."""
    config_path = path or config_dir() / "arqen.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mission = data.get("mission", {})
    return dict(mission) if isinstance(mission, dict) else {}
    return applied
