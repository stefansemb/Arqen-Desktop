from arqen.providers.base import AIProvider
from arqen.providers.config import ProviderConfig
from arqen.providers.demo import DemoProvider
from arqen.providers.local import LocalProvider
from arqen.providers.cloud import OpenAICompatibleProvider, GeminiProvider, ClaudeProvider
from arqen.providers.remote import ArqenRemoteProvider
from arqen.config.settings import load_provider_profile
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


class FallbackProvider(AIProvider):
    supports_tools = False

    def __init__(self, primary: AIProvider, fallback: AIProvider, timeout: float = 90.0) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider_name = getattr(primary, "provider_name", "local")
        self.model = getattr(primary, "model", "")
        self.fallback_used = False
        self.fallback_reason = ""
        self.timeout = timeout
        # The wrapper can only promise native tools when the fallback can
        # handle the same protocol too; otherwise a primary failure would
        # make the engine pass unsupported tool arguments to the fallback.
        self.supports_tools = bool(
            getattr(primary, "supports_tools", False)
            and getattr(fallback, "supports_tools", False)
        )

    def _run(self, operation, messages):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arqen-primary")
        future = executor.submit(operation, messages)
        try:
            return future.result(timeout=self.timeout)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _use_fallback(self, messages, exc):
        error_lines = str(exc).splitlines()
        self.fallback_reason = (error_lines[0] if error_lines else exc.__class__.__name__)[:120]
        response = self.fallback.respond(messages)
        self.fallback_used = True
        self.provider_name = getattr(self.fallback, "provider_name", "fallback")
        self.model = getattr(self.fallback, "model", "")
        return response

    def respond(self, messages):
        self.fallback_used = False
        self.fallback_reason = ""
        try:
            response = self._run(self.primary.respond, messages)
            self.provider_name = getattr(self.primary, "provider_name", "local")
            self.model = getattr(self.primary, "model", "")
            return response
        except Exception as exc:
            return self._use_fallback(messages, exc)

    def respond_stream(
        self,
        messages,
        on_chunk: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        tools=None,
    ):
        self.fallback_used = False
        self.fallback_reason = ""

        def primary_call(items):
            return self.primary.respond_stream(items, on_chunk, should_cancel, tools)

        try:
            response = self._run(primary_call, messages)
            self.provider_name = getattr(self.primary, "provider_name", "local")
            self.model = getattr(self.primary, "model", "")
            return response
        except Exception as exc:
            if hasattr(self.fallback, "respond_stream"):
                def fallback_call(items):
                    return self.fallback.respond_stream(items, on_chunk, should_cancel, tools)
                response = self._run(fallback_call, messages)
            else:
                response = self.fallback.respond(messages)
            self.fallback_used = True
            self.fallback_reason = str(exc).splitlines()[0][:120] if str(exc) else exc.__class__.__name__
            self.provider_name = getattr(self.fallback, "provider_name", "fallback")
            self.model = getattr(self.fallback, "model", "")
            return response


def create_provider(config: ProviderConfig) -> AIProvider:
    if config.name == "demo":
        primary = DemoProvider()
    elif config.name == "local":
        primary = LocalProvider(base_url=config.base_url, model=config.model, timeout=config.timeout, api_key=config.api_key)
    elif config.name == "arqen-remote":
        primary = ArqenRemoteProvider(config.base_url, config.timeout, config.api_key, config.model)
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
