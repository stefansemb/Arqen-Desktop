import json
import shutil
import uuid
from pathlib import Path


class FileUndoStore:
    """Stores the previous state of files before a mutation."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path("data") / "undo"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "last.json"

    def snapshot(self, path: Path, operation: str = "write", destination: Path | None = None) -> None:
        record_id = uuid.uuid4().hex
        backup = self.base_dir / f"{record_id}.bak"
        existed = path.exists()
        if existed:
            shutil.copy2(path, backup)
        self.index_path.write_text(
            json.dumps({
                "path": str(path),
                "backup": str(backup),
                "existed": existed,
                "operation": operation,
                "destination": str(destination) if destination else "",
            }, indent=2),
            encoding="utf-8",
        )

    def restore_last(self) -> str:
        if not self.index_path.exists():
            return "There is no file change to undo."
        record = json.loads(self.index_path.read_text(encoding="utf-8"))
        path = Path(record["path"])
        backup = Path(record["backup"])
        operation = record.get("operation", "write")
        destination = Path(record["destination"]) if record.get("destination") else None
        if operation == "move" and destination and destination.exists():
            destination.rename(path)
        elif record.get("existed") and backup.exists():
            shutil.copy2(backup, path)
        elif path.exists():
            path.unlink()
        self.index_path.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        return f"Undid file change: {path.name}"
