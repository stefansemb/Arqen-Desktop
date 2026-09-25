from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from arqen.config import paths

# Words that say nothing about what a memory is about.  Without them "vad
# heter min hund" would match every memory that also contains "min".
_STOPWORDS = frozenset("""
    att av den det din där efter eller en ett för från har hon han hur här
    inte jag kan med men mig min mina mitt nu när och om på sig sin som
    till under upp ut vad var vem vi vid vår är även också ska skulle vill
    the and for are you your with that this what who how was have has not
""".split())


def _terms(text: str) -> set[str]:
    """The content words of ``text``, lowercased, without stopwords."""
    return {
        word for word in re.findall(r"\w+", text.casefold())
        if len(word) >= 3 and word not in _STOPWORDS and not word.isdigit()
    }


def _overlap(query: set[str], content: set[str]) -> int:
    """How many query words appear in the content, counting inflections.

    Swedish inflects by adding endings, so "hunden" should find "hund":
    a word of four letters or more matches any word it is a prefix of,
    or that is a prefix of it.
    """
    matched = 0
    for term in query:
        for word in content:
            if term == word or (min(len(term), len(word)) >= 4
                                and (term.startswith(word) or word.startswith(term))):
                matched += 1
                break
    return matched


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

    def recall(self, query: str = "", *, limit: int | None = None,
               include_proposed: bool = False) -> list[Memory]:
        """Approved memories relevant to ``query``, best match first.

        Proposed memories are left out unless asked for: only what the user
        approved may be presented to the model as memory.  With no query every
        approved memory is returned, ordered by confidence.
        """
        allowed = {"approved", "proposed"} if include_proposed else {"approved"}
        records = [item for item in self.records() if item.status in allowed]
        if query.strip():
            # A query made only of stopwords has nothing to match, which is
            # not the same as no query: it recalls nothing rather than all.
            terms = _terms(query)
            scored = [(_overlap(terms, _terms(item.content)), item) for item in records]
            scored = [(score, item) for score, item in scored if score]
            scored.sort(key=lambda pair: (pair[0], pair[1].confidence), reverse=True)
            records = [item for _, item in scored]
        else:
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

