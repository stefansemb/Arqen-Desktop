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


@dataclass(frozen=True)
class Connector:
    """One card in Connections: a named set of tools and how it signs in."""

    id: str
    name: str
    category: str
    description: str
    tools: tuple[str, ...]
    # "none" for built-in groups; "token" for key-based integrations; later "oauth" or "mcp".
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

    @property
    def badge(self) -> str:
        return self.icon or self.name[:1].upper()

    def is_connected(self) -> bool:
        if not self.fields:
            return True
        from arqen.connectors.store import load_credentials

        values = load_credentials(self.id)
        return all(values.get(item.name, "").strip() for item in self.fields)

    def is_paused(self) -> bool:
        from arqen.connectors.store import load_settings

        return bool(load_settings(self.id).get("paused", False))

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
