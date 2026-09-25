"""Connections: packages of tools that can be granted to agents.

A connector bundles the tools one integration gives, together with how it is
signed in to.  Phase 1 has only the built-in groups; external integrations
(GitHub, Discord/Telegram, later OAuth and MCP) will each add a module here.
"""

from arqen.connectors.base import Connector, GrantState, grant_state, with_connector, without_connector
from arqen.connectors.registry import all_connectors

__all__ = [
    "Connector",
    "GrantState",
    "all_connectors",
    "grant_state",
    "with_connector",
    "without_connector",
]
