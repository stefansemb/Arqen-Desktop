from dataclasses import dataclass
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class ToolRequest:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    tool_request: ToolRequest | None = None

