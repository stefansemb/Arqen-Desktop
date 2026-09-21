import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from arqen.core.contracts import Message, ProviderResponse
from arqen.providers.base import AIProvider


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, base_url: str, model: str, timeout: float, api_key: str, provider_name: str = "cloud") -> None:
        self.base_url, self.model, self.timeout, self.api_key, self.provider_name = base_url.rstrip("/"), model, timeout, api_key, provider_name

    def respond(self, messages: list[Message]) -> ProviderResponse:
        # Tool results are stored internally as ``role=tool`` without the
        # provider-specific tool_call_id/name metadata.  That is fine for the
        # local engine, but OpenRouter/OpenAI-compatible gateways reject such
        # messages.  Preserve the result as ordinary context instead.
        chat_messages = []
        for message in messages:
            if message.role == "tool":
                chat_messages.append({
                    "role": "user",
                    "content": f"Tool result:\n{message.content}",
                })
            else:
                chat_messages.append({"role": message.role, "content": message.content})
        payload = {"model": self.model, "messages": chat_messages}
        request = Request(f"{self.base_url}/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError) as exc:
            detail = exc.read().decode("utf-8", errors="replace") if isinstance(exc, HTTPError) else str(exc)
            raise RuntimeError(f"{self.provider_name} provider error: {detail}") from exc
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"{self.provider_name} provider returned no choices")
        message = choices[0].get("message", {})
        content = message.get("content", "") if isinstance(message, dict) else ""
        if not content:
            raise RuntimeError(f"{self.provider_name} provider returned an empty response")
        return ProviderResponse(content=str(content).strip())


class GeminiProvider(AIProvider):
    def __init__(self, base_url: str, model: str, timeout: float, api_key: str) -> None:
        self.base_url, self.model, self.timeout, self.api_key = base_url.rstrip("/"), model, timeout, api_key

    def respond(self, messages: list[Message]) -> ProviderResponse:
        contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]} for m in messages if m.role != "tool"]
        payload = {"contents": contents}
        url = f"{self.base_url}/models/{quote(self.model, safe='')}:generateContent?key={quote(self.api_key)}"
        request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise RuntimeError("gemini provider returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [part.get("text", "") for part in parts if part.get("text")]
        if text_parts:
            return ProviderResponse(content="".join(text_parts).strip())
        for part in parts:
            function_call = part.get("functionCall")
            if function_call:
                return ProviderResponse(content=json.dumps({
                    "tool_call": {
                        "name": function_call.get("name", ""),
                        "arguments": function_call.get("args", {}),
                    }
                }))
        raise RuntimeError("Gemini returned no readable text")


class ClaudeProvider(AIProvider):
    def __init__(self, base_url: str, model: str, timeout: float, api_key: str) -> None:
        self.base_url, self.model, self.timeout, self.api_key = base_url.rstrip("/"), model, timeout, api_key

    def respond(self, messages: list[Message]) -> ProviderResponse:
        system = "\n".join(m.content for m in messages if m.role == "system")
        payload = {"model": self.model, "max_tokens": 4096, "system": system, "messages": [{"role": m.role, "content": m.content} for m in messages if m.role in {"user", "assistant"}]}
        request = Request(f"{self.base_url}/messages", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        blocks = data.get("content", [])
        text_parts = [block.get("text", "") for block in blocks if block.get("type") == "text" and block.get("text")]
        if text_parts:
            return ProviderResponse(content="".join(text_parts).strip())
        for block in blocks:
            if block.get("type") == "tool_use":
                return ProviderResponse(content=json.dumps({
                    "tool_call": {
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {}),
                    }
                }))
        raise RuntimeError("Claude returned no readable text")
