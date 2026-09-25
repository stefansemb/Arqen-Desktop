from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Connector:
    """One card in Connections: a named set of tools and how it signs in."""

    id: str
    name: str
    category: str
    description: str
    tools: tuple[str, ...]
    # "none" for built-in groups; later "token", "oauth" or "mcp".
    auth: str = "none"
    builtin: bool = True
    icon: str = ""

    @property
    def badge(self) -> str:
        return self.icon or self.name[:1].upper()


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
