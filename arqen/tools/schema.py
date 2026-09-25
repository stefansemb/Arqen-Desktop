"""Translate the Arqen tool registry into OpenAI-style function schemas.

Providers that support native function calling send these alongside the
messages, so the model is told which tools exist instead of having to guess a
calling convention from the system prompt.
"""

import re
from typing import Any, Iterable

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


def build_tool_schemas(registry: ToolRegistry, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Return the registry as an OpenAI ``tools`` array."""
    selected = set(names) if names is not None else None
    schemas: list[dict[str, Any]] = []
    for tool in registry.describe():
        if selected is not None and tool["name"] not in selected:
            continue
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


def build_relevant_tool_schemas(
    registry: ToolRegistry,
    context: str,
    already_used: Iterable[str] = (),
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Select a conservative subset of schemas for a long tool catalogue.

    Short catalogues remain unchanged. For larger ones, tools are ranked by
    words shared with the user's context. If no useful signal is found, the
    complete catalogue is retained rather than risking a missing capability.
    Tools already used during this turn are always retained.
    """
    entries = registry.describe()
    if len(entries) <= limit:
        return build_tool_schemas(registry)

    words = set(re.findall(r"[\wåäöÅÄÖ-]{3,}", context.casefold()))
    used = set(already_used)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for entry in entries:
        searchable = " ".join((entry["name"], entry["description"], *entry["arguments"])).casefold()
        score = sum(1 for word in words if word in searchable)
        if entry["name"] in used:
            score += 100
        ranked.append((score, entry))

    matches = [entry for score, entry in ranked if score > 0]
    if not matches:
        return build_tool_schemas(registry)
    selected = [entry["name"] for _, entry in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]
    selected.extend(used)
    # Some tools answer to what the user says about themselves rather than to
    # a request, so no word overlap can be expected to pick them.
    selected.extend(
        entry["name"] for entry in entries
        if getattr(registry.get(entry["name"]), "always_offered", False)
    )
    return build_tool_schemas(registry, selected)


def _argument_types(registry: ToolRegistry, name: str) -> dict[str, type]:
    tool = registry.get(name)
    return dict(tool.arguments_schema) if tool is not None else {}
