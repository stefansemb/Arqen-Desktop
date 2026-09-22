"""Translate the Arqen tool registry into OpenAI-style function schemas.

Providers that support native function calling send these alongside the
messages, so the model is told which tools exist instead of having to guess a
calling convention from the system prompt.
"""

from typing import Any

from arqen.tools.registry import ToolRegistry


_JSON_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(python_type: type) -> str:
    return _JSON_TYPES.get(python_type, "string")


def build_tool_schemas(registry: ToolRegistry) -> list[dict[str, Any]]:
    """Return the registry as an OpenAI ``tools`` array."""
    schemas: list[dict[str, Any]] = []
    for tool in registry.describe():
        properties = {
            name: {"type": _json_type(kind)}
            for name, kind in _argument_types(registry, tool["name"]).items()
        }
        description = tool["description"]
        if tool["requires_confirmation"]:
            description += " (requires user confirmation before it runs)"
        schemas.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                },
            },
        })
    return schemas


def _argument_types(registry: ToolRegistry, name: str) -> dict[str, type]:
    tool = registry.get(name)
    return dict(tool.arguments_schema) if tool is not None else {}
