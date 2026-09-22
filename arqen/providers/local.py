import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from arqen.core.contracts import Message, ProviderResponse
from arqen.providers.base import AIProvider


class LocalProvider(AIProvider):
    """OpenAI-compatible local provider for Ollama, LM Studio and similar tools."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        model: str = "qwen3:8b",
        timeout: float = 60.0,
        api_key: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key

    def respond(self, messages: list[Message]) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": 0.7,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except OSError:
                detail = ""
            raise RuntimeError(
                f"Local AI provider HTTP {exc.code} at {self.base_url}: {detail or exc.reason}"
            ) from exc
        except (OSError, URLError) as exc:
            raise RuntimeError(
                f"Local AI provider unavailable at {self.base_url}: {exc}"
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Local AI provider returned an invalid response") from exc
        return ProviderResponse(content=str(content).strip())

    def respond_stream(
        self,
        messages: list[Message],
        on_chunk: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        tools: list[dict] | None = None,
    ) -> ProviderResponse:
        payload = {"model": self.model, "messages": [{"role": m.role, "content": m.content} for m in messages], "temperature": 0.7, "stream": True}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(f"{self.base_url}/chat/completions", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        parts: list[str] = []
        try:
            with urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    if should_cancel is not None and should_cancel():
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        parts.append(str(delta))
                        if on_chunk:
                            on_chunk(str(delta))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Local AI provider HTTP {exc.code} at {self.base_url}: {detail or exc.reason}") from exc
        except (OSError, URLError) as exc:
            raise RuntimeError(f"Local AI provider unavailable at {self.base_url}: {exc}") from exc
        return ProviderResponse(content="".join(parts).strip())
