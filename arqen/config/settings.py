import json
import re
from dataclasses import asdict
from pathlib import Path

from arqen.providers.config import ProviderConfig


DEFAULT_CONFIG = ProviderConfig()


def load_api_key(provider_name: str) -> str:
    secrets_path = Path("config") / "arqen-secrets.json"
    if not secrets_path.exists():
        return ""
    try:
        secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        return str(secrets.get("providers", {}).get(provider_name, secrets.get("api_key", "")))
    except (OSError, json.JSONDecodeError):
        return ""


def load_provider_config(path: Path | None = None) -> ProviderConfig:
    config_path = path or Path("config") / "arqen.json"
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
    secrets_path = Path("config") / "arqen-secrets.json"
    api_key = ""
    if secrets_path.exists():
        try:
            secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
            providers = secrets.get("providers", {})
            api_key = str(providers.get(provider.get("name", DEFAULT_CONFIG.name), secrets.get("api_key", "")))
        except (OSError, json.JSONDecodeError):
            api_key = ""
    return ProviderConfig(
        name=provider_name,
        base_url=str(provider.get("base_url", DEFAULT_CONFIG.base_url)),
        model=re.sub(r"^\[[^\]]+\]\s*", "", str(provider.get("model", DEFAULT_CONFIG.model))),
        timeout=float(provider.get("timeout", DEFAULT_CONFIG.timeout)),
        api_key=api_key,
        fallback_enabled=bool(data.get("fallback", {}).get("enabled", False)),
        fallback_provider=str(data.get("fallback", {}).get("provider", "")),
        fallback_timeout=float(data.get("fallback", {}).get("timeout", 10.0)),
        profile_name=str(data.get("profile", "")),
    )


def load_provider_profile(provider_name: str, path: Path | None = None) -> ProviderConfig:
    """Load a saved provider profile, including its provider-specific key."""
    config_path = path or Path("config") / "arqen.json"
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
    config_path = path or Path("config") / "arqen.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {key: value for key, value in asdict(config).items() if key != "api_key"}
    profile["model"] = re.sub(r"^\[[^\]]+\]\s*", "", str(profile["model"]))
    data: dict = {
        "provider": profile,
        "profile": config.profile_name,
        "providers": {config.name: profile},
        "fallback": {
            "enabled": config.fallback_enabled,
            "provider": config.fallback_provider,
            "timeout": config.fallback_timeout,
        },
    }
    if config_path.exists():
        try:
            old = json.loads(config_path.read_text(encoding="utf-8"))
            data["providers"] = old.get("providers", {})
            data["providers"][config.name] = profile
            data["fallback"] = old.get("fallback", data["fallback"])
        except (OSError, json.JSONDecodeError):
            pass
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    secrets_path = config_path.parent / "arqen-secrets.json"
    secrets: dict = {}
    if secrets_path.exists():
        try:
            secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            secrets = {}
    providers = secrets.get("providers", {})
    providers[config.name] = config.api_key
    secrets_path.write_text(json.dumps({"providers": providers}, indent=2) + "\n", encoding="utf-8")
