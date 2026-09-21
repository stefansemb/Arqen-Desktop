from typing import Any

from arqen.tools.base import Tool
from arqen.tools.registry import ToolRegistry


class MetadataTool(Tool):
    name = "metadata_test"
    description = "A metadata test tool."
    arguments_schema = {"count": int}

    def run(self, arguments: dict[str, Any]) -> str:
        return str(arguments["count"])


def test_registry_exposes_tool_metadata() -> None:
    registry = ToolRegistry()
    registry.register(MetadataTool())
    details = registry.describe()[0]
    assert details["arguments"] == {"count": "int"}
    assert "count: int" in registry.prompt_description()
