from arqen.tools.builtins import create_builtin_registry
from arqen.tools.executor import ToolExecutor


def test_system_status_is_read_only() -> None:
    result = ToolExecutor(create_builtin_registry()).execute("system_status")
    assert result.ok is True
    assert "OS:" in result.output


def test_unknown_tool_is_rejected() -> None:
    result = ToolExecutor(create_builtin_registry()).execute("delete_file")
    assert result.ok is False
    assert "Unknown tool" in result.output

