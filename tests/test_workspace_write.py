from pathlib import Path

from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry
from arqen.tools.workspace_files import WriteWorkspaceFileTool


def test_write_requires_confirmation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    registry = ToolRegistry()
    registry.register(WriteWorkspaceFileTool())
    executor = ToolExecutor(registry)
    pending = executor.execute("write_workspace_file", {"path": "note.txt", "content": "Hej"})
    assert pending.confirmation_required is True
    assert not (tmp_path / "note.txt").exists()
    result = executor.confirm_pending(True)
    assert result.ok is True
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "Hej"
