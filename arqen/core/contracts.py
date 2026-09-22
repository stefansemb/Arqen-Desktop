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


@dataclass
class Usage:
    """What one turn cost, summed over every provider call it took.

    A turn that calls tools talks to the provider several times, so these
    accumulate rather than describe a single request.  ``cost`` is in USD and
    comes from the gateway; providers that do not report one leave it at zero.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, reported: dict[str, Any] | None) -> None:
        """Fold one provider's ``usage`` block into the running total."""
        if not isinstance(reported, dict):
            return
        self.prompt_tokens += int(reported.get("prompt_tokens") or 0)
        self.completion_tokens += int(reported.get("completion_tokens") or 0)
        try:
            self.cost += float(reported.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    tool_request: ToolRequest | None = None
    tool_calls: tuple[dict[str, Any], ...] = field(default=())
    usage: dict[str, Any] | None = None
