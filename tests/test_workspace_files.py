from pathlib import Path

import pytest

from arqen.tools.workspace_files import ReadWorkspaceFileTool


def test_read_tool_rejects_paths_outside_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    tool = ReadWorkspaceFileTool()
    with pytest.raises(PermissionError):
        tool.run({"path": "../secret.txt"})

