from typing import Any

from arqen.tools.base import Tool
from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Echoes a message."
    arguments_schema = {"message": str}

    def run(self, arguments: dict[str, Any]) -> str:
        return arguments["message"]


def make_executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return ToolExecutor(registry)


def test_valid_arguments_are_accepted() -> None:
    result = make_executor().execute("echo", {"message": "hello"})
    assert result.ok is True
    assert result.output == "hello"


def test_missing_arguments_are_rejected() -> None:
    result = make_executor().execute("echo", {})
    assert result.ok is False
    assert "Missing required argument" in result.output


def test_wrong_argument_types_are_rejected() -> None:
    result = make_executor().execute("echo", {"message": 42})
    assert result.ok is False
    assert "Invalid argument type" in result.output

