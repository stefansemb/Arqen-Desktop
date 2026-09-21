from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """Provider settings kept separate from the conversation engine."""

    name: str = "local"
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3:8b"
    timeout: float = 60.0
    api_key: str = ""
    fallback_enabled: bool = False
    fallback_provider: str = ""
    fallback_timeout: float = 10.0
    profile_name: str = ""
