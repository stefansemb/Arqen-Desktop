"""The integrations that sign in to an outside service."""

from __future__ import annotations

from arqen.connectors.base import Connector
from arqen.connectors.github import CONNECTOR as GITHUB
from arqen.connectors.messaging import DISCORD, TELEGRAM

EXTERNAL: tuple[Connector, ...] = (GITHUB, DISCORD, TELEGRAM)


def connector_by_id(connector_id: str) -> Connector | None:
    if connector_id.startswith("mcp:"):
        from arqen.connectors.mcp import mcp_connectors

        return next((item for item in mcp_connectors() if item.id == connector_id), None)
    return next((item for item in EXTERNAL if item.id == connector_id), None)
