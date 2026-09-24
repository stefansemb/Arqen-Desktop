from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from arqen.config import paths


@dataclass
class Memory:
    content: str
    source: str = "user"
    provenance: str = "explicit"
    status: str = "approved"
    confidence: float = 1.0


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.data_dir() / "memory.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def records(self) -> list[Memory]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = []
            for item in data.get("memories", []):
                if isinstance(item, str):
                    records.append(Memory(item))
                elif isinstance(item, dict) and item.get("content"):
                    records.append(Memory(
                        content=str(item["content"]),
                        source=str(item.get("source", "user")),
                        provenance=str(item.get("provenance", "explicit")),
                        status=str(item.get("status", "approved")),
                        confidence=float(item.get("confidence", 1.0)),
                    ))
            return records
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def list(self) -> list[str]:
        return [record.content for record in self.records()]

    def retain(self, fact: str, *, source: str = "user", provenance: str = "explicit",
               status: str = "approved", confidence: float = 1.0) -> Memory:
        fact = fact.strip()
        if not fact:
            raise ValueError("Memory content cannot be empty")
        memories = self.records()
        existing = next((item for item in memories if item.content == fact), None)
        record = existing or Memory(fact, source, provenance, status, max(0.0, min(1.0, confidence)))
        if existing is None:
            memories.append(record)
        self._write(memories)
        return record

    def remember(self, fact: str) -> None:
        self.retain(fact)

    def recall(self, query: str = "", *, limit: int | None = None) -> list[Memory]:
        words = {word.casefold() for word in query.split() if len(word) > 2}
        records = [item for item in self.records() if item.status != "obsolete"]
        if words:
            records = [item for item in records if words & set(item.content.casefold().split())]
        records.sort(key=lambda item: item.confidence, reverse=True)
        return records[:limit] if limit is not None else records

    def reflect(self) -> dict[str, int]:
        records = self.records()
        return {
            "total": len(records),
            "approved": sum(item.status == "approved" for item in records),
            "proposed": sum(item.status == "proposed" for item in records),
            "obsolete": sum(item.status == "obsolete" for item in records),
        }

    def _write(self, memories: list[Memory]) -> None:
        self.path.write_text(
            json.dumps({"memories": [asdict(item) for item in memories]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def forget(self, fact: str) -> bool:
        memories = self.records()
        if not any(item.content == fact for item in memories):
            return False
        memories = [item for item in memories if item.content != fact]
        self._write(memories)
        return True

    def update(self, old_fact: str, new_fact: str, *, status: str | None = None,
               confidence: float | None = None) -> bool:
        new_fact = new_fact.strip()
        if not new_fact:
            return False
        memories = self.records()
        for item in memories:
            if item.content == old_fact:
                item.content = new_fact
                if status is not None:
                    item.status = status
                if confidence is not None:
                    item.confidence = max(0.0, min(1.0, confidence))
                self._write(memories)
                return True
        return False

