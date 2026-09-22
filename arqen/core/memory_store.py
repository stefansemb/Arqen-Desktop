import json
from pathlib import Path
from arqen.config.paths import data_dir


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "memory.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [str(item) for item in data.get("memories", [])]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def remember(self, fact: str) -> None:
        fact = fact.strip()
        if not fact:
            return
        memories = self.list()
        if fact not in memories:
            memories.append(fact)
        self.path.write_text(
            json.dumps({"memories": memories}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def forget(self, fact: str) -> bool:
        memories = self.list()
        if fact not in memories:
            return False
        memories.remove(fact)
        self.path.write_text(
            json.dumps({"memories": memories}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True

