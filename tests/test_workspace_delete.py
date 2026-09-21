from pathlib import Path

from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry
from arqen.tools.workspace_files import DeleteWorkspaceFileTool


def test_delete_requires_confirmation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "remove.txt"
    target.write_text("temporary", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(DeleteWorkspaceFileTool())
    executor = ToolExecutor(registry)
    pending = executor.execute("delete_workspace_file", {"path": "remove.txt"})
    assert pending.confirmation_required is True
    assert target.exists()
    result = executor.confirm_pending(True)
    assert result.ok is True
    assert not target.exists()
