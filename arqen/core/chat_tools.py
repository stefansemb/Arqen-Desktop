"""Which tools the chat -- Arqen itself -- may use.

Chosen on the Connections view, like an agent's tools.  An agent keeps a list
of the tools it has; the chat keeps a list of the tools taken away from it
(``arqen.json`` → ``"chat"`` → ``"denied_tools"``), so a tool that arrives
later -- a new connection, an MCP server -- is the chat's at once, as it
always was.

The limit belongs to the chat engines only (the app, the command line and the
local API).  Task engines are built without it and follow their agent.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from arqen.config import paths

if TYPE_CHECKING:
    from arqen.core.engine import ConversationEngine
    from arqen.tools.registry import ToolRegistry


def _config_path():
    # Looked up on each call so tests can point it at their own directory.
    return paths.config_dir() / "arqen.json"


def _read() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_denied_tools() -> tuple[str, ...]:
    chat = _read().get("chat")
    denied = chat.get("denied_tools") if isinstance(chat, dict) else None
    return tuple(str(name) for name in denied) if isinstance(denied, list) else ()


def save_denied_tools(names) -> None:
    """Keep the rest of ``arqen.json`` as it is; it is shared with all of Arqen."""
    data = _read()
    chat = data.get("chat") if isinstance(data.get("chat"), dict) else {}
    chat["denied_tools"] = sorted(set(names))
    data["chat"] = chat
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def chat_allowed_tools(registry: ToolRegistry) -> tuple[str, ...]:
    """Every tool in ``registry`` the chat has not had taken away."""
    denied = set(load_denied_tools())
    return tuple(item["name"] for item in registry.describe() if item["name"] not in denied)


def apply_chat_tool_limits(engine: ConversationEngine) -> None:
    """Make ``engine`` a chat engine: the taken-away tools are neither offered nor run."""
    from arqen.tools.gateway import ToolPolicy

    engine.gateway.set_policy("default", ToolPolicy(denied_tools=frozenset(load_denied_tools())))
