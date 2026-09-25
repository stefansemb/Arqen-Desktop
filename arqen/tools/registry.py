from typing import Any

from arqen.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "requires_confirmation": tool.requires_confirmation,
                "arguments": {
                    name: expected_type.__name__
                    for name, expected_type in tool.arguments_schema.items()
                },
            }
            for tool in self._tools.values()
        ]

    def prompt_description(self) -> str:
        """Return a compact, provider-neutral description of available tools."""
        lines = []
        for tool in self._tools.values():
            if not tool.available():
                continue
            own_schema = getattr(tool, "json_schema", None)
            if isinstance(own_schema, dict):
                arguments = ", ".join(
                    f"{name}: {spec.get('type', 'any') if isinstance(spec, dict) else 'any'}"
                    for name, spec in (own_schema.get("properties") or {}).items()
                ) or "none"
            else:
                arguments = ", ".join(
                    f"{name}: {kind.__name__}"
                    for name, kind in tool.arguments_schema.items()
                ) or "none"
            confirmation = "confirmation required" if tool.requires_confirmation else "read-only"
            lines.append(f"- {tool.name} ({confirmation}): {tool.description}; arguments: {arguments}")
        return "\n".join(lines)

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        if tool.requires_confirmation:
            raise PermissionError(f"Confirmation required before running tool: {name}")
        return tool.run(arguments or {})
