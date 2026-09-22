from pathlib import Path

import pytest

from arqen.config import paths
from arqen.core.file_undo import FileUndoStore
from arqen.tools import workspace_files


@pytest.fixture(autouse=True)
def sandbox_the_workspace(monkeypatch, tmp_path):
    """Keep a test inside its own directory, workspace and undo history.

    Tests sandbox themselves with ``monkeypatch.chdir(tmp_path)``.  In
    production the workspace comes from the saved setting rather than the
    working directory, so the tools have to be pointed at the test's
    directory explicitly or they would reach past it into the checkout.

    The undo store is a module-level singleton anchored to the app's own
    data directory, which is shared with the running app -- a test must not
    overwrite the undo history of whoever is using Arqen.
    """
    monkeypatch.setattr(paths, "workspace_root", lambda: Path.cwd().resolve())
    monkeypatch.setattr(workspace_files, "UNDO", FileUndoStore(tmp_path / "undo"))
