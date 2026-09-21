from pathlib import Path

from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry
from arqen.tools.workspace_files import MoveWorkspaceFileTool


def test_move_requires_confirmation_and_refuses_overwrite(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "old.txt"
    source.write_text("content", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(MoveWorkspaceFileTool())
    executor = ToolExecutor(registry)
    pending = executor.execute(
        "move_workspace_file",
        {"source": "old.txt", "destination": "new.txt"},
    )
    assert pending.confirmation_required is True
    result = executor.confirm_pending(True)
    assert result.ok is True
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "content"
