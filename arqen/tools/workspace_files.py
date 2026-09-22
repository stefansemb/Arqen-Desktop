from pathlib import Path
from typing import Any

from arqen.tools.base import Tool
from arqen.core.file_undo import FileUndoStore
from arqen.config import paths


UNDO = FileUndoStore()


def describe_size(path: Path) -> str:
    """A file's size, so listings can be compared without reading them.

    Asked which of several files is shortest, a model that only gets names
    has to open every one of them; with sizes it answers from the listing.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return "?"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} kB"
    return f"{size / (1024 * 1024):.1f} MB"


class WorkspaceFilesTool(Tool):
    name = "workspace_files"
    description = "Lists files and their sizes in the Arqen workspace root."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        entries = sorted(
            path.name + "/" if path.is_dir() else f"{path.name}\t{describe_size(path)}"
            for path in root.iterdir()
            if path.name not in {".git", "__pycache__", ".venv"}
        )
        return "\n".join(entries[:100]) or "Workspace is empty."


class SearchWorkspaceFilesTool(Tool):
    name = "search_workspace_files"
    description = "Searches recursively for file names and sizes inside the Arqen workspace."
    requires_confirmation = False
    arguments_schema = {"query": str}

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        query = arguments["query"].strip().lower()
        if not query:
            raise ValueError("Search query cannot be empty")
        ignored = {".git", "__pycache__", ".venv", "venv", "data"}
        results = []
        for path in root.rglob("*"):
            if any(part in ignored for part in path.parts):
                continue
            if path.is_file() and query in path.name.lower():
                results.append(f"{path.relative_to(root)}\t{describe_size(path)}")
            if len(results) >= 100:
                break
        return "\n".join(results) or f"No files found for: {query}"


class SearchWorkspaceContentTool(Tool):
    name = "search_workspace_content"
    description = "Searches text file contents inside the Arqen workspace."
    requires_confirmation = False
    arguments_schema = {"query": str}

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        query = arguments["query"].strip().lower()
        if not query:
            raise ValueError("Content search query cannot be empty")
        ignored = {".git", "__pycache__", ".venv", "venv", "data"}
        extensions = {".txt", ".md", ".json", ".py", ".ps1", ".bat", ".toml", ".yaml", ".yml"}
        results = []
        for path in root.rglob("*"):
            if len(results) >= 100 or any(part in ignored for part in path.parts):
                continue
            if not path.is_file() or path.suffix.lower() not in extensions or path.stat().st_size > 512_000:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(lines, 1):
                if query in line.lower():
                    results.append(f"{path.relative_to(root)}:{line_number}: {line.strip()[:200]}")
                    if len(results) >= 100:
                        break
        return "\n".join(results) or f"No content found for: {query}"


class ReadWorkspaceFileTool(Tool):
    name = "read_workspace_file"
    description = "Reads a UTF-8 text file inside the Arqen workspace."
    requires_confirmation = False
    arguments_schema = {"path": str}

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        candidate = (root / arguments["path"]).resolve()
        if root not in candidate.parents and candidate != root:
            raise PermissionError("Path is outside the Arqen workspace")
        if not candidate.is_file():
            raise FileNotFoundError(f"File not found: {arguments['path']}")
        if candidate.stat().st_size > 512_000:
            raise ValueError("File is larger than the 512 KB read limit")
        return candidate.read_text(encoding="utf-8")


class WriteWorkspaceFileTool(Tool):
    name = "write_workspace_file"
    description = "Creates or overwrites a UTF-8 text file inside the Arqen workspace."
    requires_confirmation = True
    arguments_schema = {"path": str, "content": str}

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        candidate = (root / arguments["path"]).resolve()
        if root not in candidate.parents:
            raise PermissionError("Path is outside the Arqen workspace")
        content = arguments["content"]
        if len(content.encode("utf-8")) > 512_000:
            raise ValueError("Content is larger than the 512 KB write limit")
        UNDO.snapshot(candidate, operation="write")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")
        return f"Wrote file: {candidate.relative_to(root)}"


class DeleteWorkspaceFileTool(Tool):
    name = "delete_workspace_file"
    description = "Deletes a file inside the Arqen workspace."
    requires_confirmation = True
    arguments_schema = {"path": str}

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        candidate = (paths.workspace_root() / arguments["path"]).resolve()
        if not candidate.is_file():
            return f"File not found: {arguments['path']}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        candidate = (root / arguments["path"]).resolve()
        if root not in candidate.parents:
            raise PermissionError("Path is outside the Arqen workspace")
        if not candidate.is_file():
            raise FileNotFoundError(f"File not found: {arguments['path']}")
        UNDO.snapshot(candidate, operation="delete")
        candidate.unlink()
        return f"Deleted file: {candidate.relative_to(root)}"


class MoveWorkspaceFileTool(Tool):
    name = "move_workspace_file"
    description = "Moves or renames a file inside the Arqen workspace."
    requires_confirmation = True
    arguments_schema = {"source": str, "destination": str}

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        root = paths.workspace_root()
        source = (root / arguments["source"]).resolve()
        destination = (root / arguments["destination"]).resolve()
        if not source.is_file():
            return f"Source file not found: {arguments['source']}"
        if destination.exists():
            return f"Destination already exists: {arguments['destination']}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        root = paths.workspace_root()
        source = (root / arguments["source"]).resolve()
        destination = (root / arguments["destination"]).resolve()
        if root not in source.parents or root not in destination.parents:
            raise PermissionError("Source and destination must be inside the Arqen workspace")
        if not source.is_file():
            raise FileNotFoundError(f"Source file not found: {arguments['source']}")
        if destination.exists():
            raise FileExistsError(f"Destination already exists: {arguments['destination']}")
        UNDO.snapshot(source, operation="move", destination=destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return f"Moved file: {source.relative_to(root)} -> {destination.relative_to(root)}"


class UndoWorkspaceFileTool(Tool):
    name = "undo_workspace_file_change"
    description = "Restores the most recent file mutation in the Arqen workspace."
    requires_confirmation = True

    def run(self, arguments: dict[str, Any]) -> str:
        return UNDO.restore_last()
