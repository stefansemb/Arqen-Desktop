from arqen.core.contracts import Message, ProviderResponse, ToolRequest
from arqen.providers.base import AIProvider


class DemoProvider(AIProvider):
    """Deterministic provider used to validate the core without credentials."""

    def respond(self, messages: list[Message]) -> ProviderResponse:
        latest = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if latest.lower() in {"systemstatus", "system status", "systemstatus?"}:
            return ProviderResponse(
                content="",
                tool_request=ToolRequest(name="system_status", arguments={}),
            )
        return ProviderResponse(content=f"Jag tog emot: {latest}")
