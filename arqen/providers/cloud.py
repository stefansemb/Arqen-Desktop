import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from arqen.core.contracts import Message, ProviderResponse, ToolRequest
from arqen.providers.base import AIProvider


class OpenAICompatibleProvider(AIProvider):
    """OpenAI-compatible cloud provider with streaming and native tool calls."""

    supports_tools = True

    def __init__(self, base_url: str, model: str, timeout: float, api_key: str, provider_name: str = "cloud") -> None:
        self.base_url, self.model, self.timeout, self.api_key, self.provider_name = base_url.rstrip("/"), model, timeout, api_key, provider_name

    # -- request building -------------------------------------------------

    def _chat_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        chat: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                if message.tool_call_id:
                    chat.append({
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    })
                else:
                    # Without a call id the result came from the keyword
                    # fallback rather than a model-issued call.  Gateways
                    # reject bare tool messages, so keep it as ordinary
                    # context instead.
                    chat.append({"role": "user", "content": f"Tool result:\n{message.content}"})
                continue
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.role == "assistant" and message.tool_calls:
                entry["tool_calls"] = list(message.tool_calls)
            chat.append(entry)
        return chat

    def _request(self, messages: list[Message], tools: list[dict[str, Any]] | None, stream: bool) -> Request:
        payload: dict[str, Any] = {"model": self.model, "messages": self._chat_messages(messages)}
        # GPT-5.6 rejects function tools in Chat Completions unless reasoning
        # is explicitly disabled.  Responses API support can be added later;
        # this keeps the existing streaming/tool protocol working meanwhile.
        if self.model.casefold().startswith("gpt-5.6"):
            payload["reasoning_effort"] = "none"
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )

    def _fail(self, exc: Exception) -> RuntimeError:
        detail = exc.read().decode("utf-8", errors="replace") if isinstance(exc, HTTPError) else str(exc)
        return RuntimeError(f"{self.provider_name} provider error: {detail}")

    # -- responses --------------------------------------------------------

    def respond(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> ProviderResponse:
        try:
            with urlopen(self._request(messages, tools, stream=False), timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError) as exc:
            raise self._fail(exc) from exc
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"{self.provider_name} provider returned no choices")
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            raise RuntimeError(f"{self.provider_name} provider returned an unreadable message")
        return self._build(message.get("content") or "", message.get("tool_calls") or [], data.get("usage"))

    def respond_stream(
        self,
        messages: list[Message],
        on_chunk: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] | None = None
        try:
            with urlopen(self._request(messages, tools, stream=True), timeout=self.timeout) as response:
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
                    if event.get("usage"):
                        # Arrives in a trailing chunk of its own, after the
                        # content is done and often with no choices at all.
                        usage = event["usage"]
                    choices = event.get("choices") or [{}]
                    delta = choices[0].get("delta", {})
                    if not isinstance(delta, dict):
                        continue
                    text = delta.get("content")
                    if text:
                        parts.append(str(text))
                        if on_chunk:
                            on_chunk(str(text))
                    for fragment in delta.get("tool_calls") or []:
                        self._merge_call(calls, fragment)
        except (HTTPError, URLError, OSError) as exc:
            raise self._fail(exc) from exc
        ordered = [calls[index] for index in sorted(calls)]
        if should_cancel is not None and should_cancel():
            return ProviderResponse(content="".join(parts).strip(), usage=usage)
        return self._build("".join(parts), ordered, usage)

    @staticmethod
    def _merge_call(calls: dict[int, dict[str, Any]], fragment: dict[str, Any]) -> None:
        """Accumulate one streamed tool-call delta into the call it belongs to."""
        if not isinstance(fragment, dict):
            return
        index = fragment.get("index", 0)
        call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        if fragment.get("id"):
            call["id"] = fragment["id"]
        function = fragment.get("function")
        if isinstance(function, dict):
            # Both the name and the argument JSON can arrive split across
            # deltas, so append rather than replace.
            if function.get("name"):
                call["function"]["name"] += function["name"]
            if function.get("arguments"):
                call["function"]["arguments"] += function["arguments"]

    def _build(self, content: str, raw_calls: list[dict[str, Any]], usage: dict[str, Any] | None = None) -> ProviderResponse:
        content = str(content).strip()
        request = None
        for call in raw_calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            raw_arguments = function.get("arguments")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                arguments = {}
            request = ToolRequest(name=name, arguments=arguments, call_id=call.get("id") or None)
            break
        if not content and request is None:
            raise RuntimeError(f"{self.provider_name} provider returned an empty response")
        return ProviderResponse(content=content, tool_request=request, tool_calls=tuple(raw_calls), usage=usage)


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
