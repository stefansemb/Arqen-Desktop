from arqen.providers.base import AIProvider
from arqen.providers.config import ProviderConfig
from arqen.providers.demo import DemoProvider
from arqen.providers.local import LocalProvider
from arqen.providers.cloud import OpenAICompatibleProvider, GeminiProvider, ClaudeProvider
from arqen.config.settings import load_provider_profile
from concurrent.futures import ThreadPoolExecutor, TimeoutError


class FallbackProvider(AIProvider):
    def __init__(self, primary: AIProvider, fallback: AIProvider, timeout: float = 10.0) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider_name = getattr(primary, "provider_name", "local")
        self.model = getattr(primary, "model", "")
        self.fallback_used = False
        self.fallback_reason = ""
        self.timeout = timeout

    def respond(self, messages):
        self.fallback_used = False
        self.fallback_reason = ""
        try:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arqen-primary")
            future = executor.submit(self.primary.respond, messages)
            try:
                response = future.result(timeout=self.timeout)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            self.provider_name = getattr(self.primary, "provider_name", "local")
            self.model = getattr(self.primary, "model", "")
            return response
        except Exception as exc:
            error_lines = str(exc).splitlines()
            self.fallback_reason = (error_lines[0] if error_lines else exc.__class__.__name__)[:120]
            response = self.fallback.respond(messages)
            self.fallback_used = True
            self.provider_name = getattr(self.fallback, "provider_name", "fallback")
            self.model = getattr(self.fallback, "model", "")
            return response


def create_provider(config: ProviderConfig) -> AIProvider:
    if config.name == "demo":
        primary = DemoProvider()
    elif config.name == "local":
        primary = LocalProvider(base_url=config.base_url, model=config.model, timeout=config.timeout, api_key=config.api_key)
    elif config.name in {"openai", "openrouter"}:
        primary = OpenAICompatibleProvider(config.base_url, config.model, config.timeout, config.api_key, config.name)
    elif config.name == "gemini":
        primary = GeminiProvider(config.base_url, config.model, config.timeout, config.api_key)
    elif config.name == "claude":
        primary = ClaudeProvider(config.base_url, config.model, config.timeout, config.api_key)
    else:
        raise ValueError(f"Unsupported provider: {config.name}")
    if config.fallback_enabled and config.fallback_provider and config.fallback_provider != config.name:
        fallback_config = load_provider_profile(config.fallback_provider)
        return FallbackProvider(primary, create_provider(fallback_config), config.fallback_timeout)
    return primary
