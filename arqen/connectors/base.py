from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class CredentialField:
    """One thing the user types in to connect, e.g. a token."""

    name: str
    label: str
    secret: bool = True
    placeholder: str = ""
    help: str = ""
    # Finds the value from the other fields, e.g. a chat id from a bot token.
    # Returns (value, description) pairs, newest first; raises with a readable message.
    lookup: Callable[[dict[str, str]], list[tuple[str, str]]] | None = field(default=None, compare=False)
    lookup_label: str = ""


@dataclass(frozen=True)
class Connector:
    """One card in Connections: a named set of tools and how it signs in."""

    id: str
    name: str
    category: str
    description: str
    tools: tuple[str, ...]
    # "none" for built-in groups, "token" for key-based integrations, "oauth"
    # for a browser sign-in and "mcp" for the user's MCP servers.
    auth: str = "none"
    builtin: bool = True
    icon: str = ""
    fields: tuple[CredentialField, ...] = ()
    # Checks credentials against the service without side effects; returns a
    # short description of what it reached, raises with a readable message.
    test: Callable[[dict[str, str]], str] | None = field(default=None, compare=False)
    # Sends a plain message, for automatic notifications; None if it cannot.
    notify: Callable[[dict[str, str], str], None] | None = field(default=None, compare=False)
    help_url: str = ""
    # Credentials the service hands out at sign-in rather than ones the user
    # types in, e.g. an OAuth refresh token.  Needed to count as connected.
    issued: tuple[str, ...] = ()
    # Runs the browser sign-in with the typed-in fields; returns the issued
    # credentials plus non-secret details (under "settings") to keep.
    sign_in: Callable[..., dict] | None = field(default=None, compare=False)
    # Withdraws the grant at the service when disconnecting; best effort.
    sign_out: Callable[[dict[str, str]], None] | None = field(default=None, compare=False)

    @property
    def badge(self) -> str:
        return self.icon or self.name[:1].upper()

    def is_connected(self) -> bool:
        needed = [item.name for item in self.fields] + list(self.issued)
        if not needed:
            return True
        from arqen.connectors.store import load_credentials

        values = load_credentials(self.id)
        return all(values.get(name, "").strip() for name in needed)

    def is_paused(self) -> bool:
        from arqen.connectors.store import load_settings

        return bool(load_settings(self.id).get("paused", False))

    def needs_reconnect(self) -> bool:
        """Connected once, but the service no longer accepts the sign-in."""
        from arqen.connectors.store import load_settings

        return self.is_connected() and bool(load_settings(self.id).get("needs_reconnect", False))

    def is_active(self) -> bool:
        return self.is_connected() and not self.is_paused()


class GrantState(Enum):
    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


def grant_state(connector: Connector, allowed_tools: tuple[str, ...]) -> GrantState:
    """How much of ``connector`` an agent with ``allowed_tools`` can use."""
    granted = sum(tool in allowed_tools for tool in connector.tools)
    if granted == 0:
        return GrantState.NONE
    return GrantState.FULL if granted == len(connector.tools) else GrantState.PARTIAL


def with_connector(connector: Connector, allowed_tools: tuple[str, ...]) -> tuple[str, ...]:
    """``allowed_tools`` plus every tool of ``connector``, order kept."""
    return tuple(allowed_tools) + tuple(tool for tool in connector.tools if tool not in allowed_tools)


def without_connector(connector: Connector, allowed_tools: tuple[str, ...]) -> tuple[str, ...]:
    """``allowed_tools`` without the tools of ``connector``."""
    return tuple(tool for tool in allowed_tools if tool not in connector.tools)
