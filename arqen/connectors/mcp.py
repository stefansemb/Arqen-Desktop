"""MCP servers as connections, and their tools as Arqen tools.

Servers are added by the user and kept in ``config/arqen.json`` under
``"mcp_servers"``, together with the tool list fetched when the server was
last refreshed, so starting Arqen never waits on a server.  A bearer token,
if any, is a connector credential in ``arqen-secrets.json``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from arqen.config import paths
from arqen.connectors.base import Connector, CredentialField
from arqen.connectors.mcp_client import McpToolSpec, with_session
from arqen.connectors.store import load_credentials
from arqen.tools.base import Tool

_PREFIX = "mcp_"
_TITLES: dict[str, str] = {}


def _config_path():
    return paths.config_dir() / "arqen.json"


def load_servers() -> list[dict]:
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return []
    servers = data.get("mcp_servers") if isinstance(data, dict) else None
    return [server for server in servers if isinstance(server, dict) and server.get("id")] if isinstance(servers, list) else []


def save_servers(servers: list[dict]) -> None:
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    data["mcp_servers"] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def server_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "", name.casefold())[:16] or "server"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}{number}", number + 1
    return candidate


def connector_id(server: dict) -> str:
    return f"mcp:{server['id']}"


def tool_name(server: dict, name: str) -> str:
    """A function name providers accept: letters, digits, _ and -, at most 64 long."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    return f"{_PREFIX}{server['id']}_{cleaned}"[:64]


def display_title(name: str) -> str | None:
    return _TITLES.get(name)


def fetch_tools(server: dict, token: str = "") -> list[McpToolSpec]:
    """Ask the server for its tools (used when adding or refreshing it)."""
    return with_session(server, token, lambda session: session.list_tools())


class McpTool(Tool):
    """One tool of an MCP server, called through a fresh session."""

    def __init__(self, server: dict, spec: McpToolSpec) -> None:
        self.server = server
        self.spec = spec
        self.name = tool_name(server, spec.name)
        self.description = f"[{server.get('name', server['id'])}] {spec.description}".strip()
        self.connector_id = connector_id(server)
        # Unknown tools can do anything, so they ask first unless the server
        # itself says they only read.
        self.requires_confirmation = not spec.read_only
        self.json_schema = spec.input_schema
        self.arguments_schema = {}

    def validate_arguments(self, arguments: dict[str, Any]) -> str | None:
        missing = [key for key in self.json_schema.get("required", []) if key not in arguments]
        return f"Missing required argument: {', '.join(missing)}" if missing else None

    def run(self, arguments: dict[str, Any]) -> str:
        token = self.credentials().get("token", "")
        return with_session(self.server, token, lambda session: session.call(self.spec.name, arguments))


def mcp_tools() -> list[McpTool]:
    tools = []
    for server in load_servers():
        for data in server.get("tools") or []:
            try:
                tool = McpTool(server, McpToolSpec.from_json(data))
            except (KeyError, TypeError, ValueError):
                continue
            _TITLES[tool.name] = tool.spec.name
            tools.append(tool)
    return tools


def sync_mcp_tools(registry) -> None:
    """Replace the registry's MCP tools with the ones currently configured."""
    for name in [name for name in list(registry._tools) if name.startswith(_PREFIX)]:
        registry._tools.pop(name, None)
    for tool in mcp_tools():
        registry.register(tool)


def mcp_connectors() -> list[Connector]:
    connectors = []
    for server in load_servers():
        where = server.get("url") if server.get("transport") != "stdio" else f"{server.get('command', '')} {server.get('args', '')}".strip()
        tools = tuple(tool_name(server, str(tool.get("name", ""))) for tool in server.get("tools") or [] if tool.get("name"))
        connectors.append(Connector(
            id=connector_id(server),
            name=str(server.get("name") or server["id"]),
            category="MCP",
            description=f"MCP-server: {where}",
            tools=tools,
            auth="mcp",
            builtin=False,
            icon="M",
            # The token is optional, so no field is required to count as connected.
            fields=(),
        ))
    return connectors


TOKEN_FIELD = CredentialField("token", "Token (valfri)", placeholder="Bearer-token om servern kräver det")


def server_token(server: dict) -> str:
    return load_credentials(connector_id(server)).get("token", "")
