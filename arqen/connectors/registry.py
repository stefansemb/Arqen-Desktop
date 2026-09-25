from __future__ import annotations

from arqen.connectors.base import Connector
from arqen.tools.registry import ToolRegistry
from arqen.ui.tool_catalog import CATEGORIES, tool_info

# What each built-in group is for, in the words shown on its card.
_BUILTIN = {
    "System": ("system", "Datorns status, tid, resurser och processer.", "S"),
    "Fönster & program": ("windows", "Se, fokusera, starta och stänga program och fönster.", "F"),
    "Filer i arbetsytan": ("files", "Lista, söka, läsa och ändra filer i arbetsytan.", "A"),
    "Dokument": ("documents", "Läsa PDF-, Word- och Excel-filer.", "D"),
    "Webb": ("web", "Söka på webben, hämta sidor och väder.", "W"),
    "Webbläsare": ("browser", "Styra Arqens egen webbläsare: gå till, läsa, klicka.", "B"),
    "Röst & bild": ("voice-image", "Läsa upp text och skapa bilder.", "R"),
    "Minne": ("memory", "Föreslå saker att minnas; du godkänner dem.", "M"),
}


def builtin_connectors(tools: ToolRegistry) -> list[Connector]:
    """The built-in tool groups as connectors, one per catalogue category."""
    grouped: dict[str, list[str]] = {}
    for entry in tools.describe():
        tool = tools.get(entry["name"])
        if tool is not None and tool.connector_id:
            continue  # belongs to its own connection card, not a built-in group
        grouped.setdefault(tool_info(entry["name"]).category, []).append(entry["name"])
    connectors = []
    for category in CATEGORIES:
        names = grouped.get(category)
        if not names:
            continue
        identifier, description, icon = _BUILTIN.get(
            category, (category.casefold(), "Verktyg utan egen grupp.", category[:1])
        )
        connectors.append(Connector(
            id=f"builtin:{identifier}",
            name=category,
            category="Inbyggt",
            description=description,
            tools=tuple(names),
            icon=icon,
        ))
    return connectors


def all_connectors(tools: ToolRegistry) -> list[Connector]:
    """Every connector Arqen knows about, built-in first."""
    from arqen.connectors.external import EXTERNAL

    return builtin_connectors(tools) + list(EXTERNAL)
