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
        # A connection tool is only offered while its connection is active.
        implementation = registry.get(tool["name"])
        if implementation is not None and not implementation.available():
            continue
        description = tool["description"]
        if tool["requires_confirmation"]:
            description += " (requires user confirmation before it runs)"
        # MCP tools bring their own JSON schema; built-in tools are described
        # by their simple argument types.
        own_schema = getattr(implementation, "json_schema", None)
        if isinstance(own_schema, dict):
            parameters = {"type": "object", "properties": {}, **own_schema}
        else:
            properties = {
                name: {"type": _json_type(kind)}
                for name, kind in _argument_types(registry, tool["name"]).items()
            }
            parameters = {"type": "object", "properties": properties, "required": list(properties)}
        schemas.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": description,
                "parameters": parameters,
            },
        })
    return schemas


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\wåäöÅÄÖ-]{3,}", text.casefold()))


def build_relevant_tool_schemas(
    registry: ToolRegistry,
    context: str,
    already_used: Iterable[str] = (),
    limit: int = 12,
    focus: str = "",
) -> list[dict[str, Any]]:
    """Select a conservative subset of schemas for a long tool catalogue.

    Short catalogues remain unchanged. For larger ones, tools are ranked by
    words shared with ``focus`` (the latest request) and, far more weakly,
    with ``context`` (the rest of the conversation).  A word counts less the
    more tools it appears in, so a word like "Arqen" that half the catalogue
    mentions cannot crowd out "telegram", and a word in a tool's own name
    counts most.  If no useful signal is found, the complete catalogue is
    retained rather than risking a missing capability.  Tools already used
    during this turn are always retained.
    """
    entries = [entry for entry in registry.describe()
               if (tool := registry.get(entry["name"])) is None or tool.available()]
    if len(entries) <= limit:
        return build_tool_schemas(registry)

    searchable = {
        entry["name"]: " ".join((entry["name"], entry["description"], *entry["arguments"])).casefold()
        for entry in entries
    }

    def found(word: str, text: str) -> bool:
        # Swedish inflections: "kalendern", "filerna" and "mejlen" should find
        # "kalender", "filer" and "mejl".
        return word in text or (len(word) >= 6 and word[:-2] in text)

    def score(words: set[str], name: str) -> float:
        total = 0.0
        for word in words:
            if not found(word, searchable[name]):
                continue
            spread = sum(found(word, text) for text in searchable.values())
            total += (3.0 if found(word, name.casefold()) else 1.0) / spread
        return total

    focus_words, context_words = _words(focus), _words(context)
    used = set(already_used)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        # The latest request decides; the conversation only breaks ties.
        value = 10 * score(focus_words, entry["name"]) + score(context_words, entry["name"])
        if entry["name"] in used:
            value += 1000
        ranked.append((value, entry))

    matches = [entry for value, entry in ranked if value > 0]
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
