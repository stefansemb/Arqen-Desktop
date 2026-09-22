from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    # Native tool-calling metadata.  Only set when the provider supports
    # OpenAI-style function calling: ``tool_calls`` on the assistant turn that
    # requested them, ``tool_call_id`` on the matching tool result.  Providers
    # without tool support simply ignore both fields.
    tool_calls: tuple[dict[str, Any], ...] = field(default=())
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolRequest:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    tool_request: ToolRequest | None = None
    tool_calls: tuple[dict[str, Any], ...] = field(default=())
