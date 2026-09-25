import re
from typing import Any

from arqen.core.memory_store import MemoryStore
from arqen.tools.base import Tool

# Proposals are read back to the model once approved, so anything that looks
# like a credential is refused before it can reach the memory file.
_SECRET = re.compile(
    r"lösenord|password|passwd|api[\s_-]?nyckel|api[\s_-]?key|\btoken\b|\bsecret\b|pin[\s-]?kod"
    r"|\bsk-[A-Za-z0-9_-]{12,}|\b[A-Za-z0-9_-]{32,}\b",
    re.IGNORECASE,
)


class ProposeMemoryTool(Tool):
    """Suggests a memory; the user approves it before Arqen may rely on it."""

    name = "propose_memory"
    description = (
        "Suggests a lasting fact for long-term memory: a preference, a decision, a person, "
        "or a detail about the user's projects that stays true beyond this conversation. "
        "It is only a suggestion: the user approves it later under Memory, and until then "
        "it is not remembered. Do not use it for one-off requests, and never for passwords, "
        "keys or other secrets. Write the fact as one short sentence in the user's language."
    )
    always_offered = True
    arguments_schema = {"fact": str}

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store

    def _memory(self) -> MemoryStore:
        # Resolved per call, so the data directory is looked up when it is used.
        return self._store or MemoryStore()

    def validate_arguments(self, arguments: dict[str, Any]) -> str | None:
        error = super().validate_arguments(arguments)
        if error:
            return error
        fact = " ".join(arguments["fact"].split())
        if not fact:
            return "The fact is empty."
        if len(fact) > 300:
            return "The fact is too long; keep it to one short sentence."
        if _SECRET.search(fact):
            return "Not suggested: it looks like a password, key or other secret."
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        fact = " ".join(arguments["fact"].split())
        store = self._memory()
        existing = next((item for item in store.records() if item.content.casefold() == fact.casefold()), None)
        if existing is not None and existing.status == "approved":
            return f"Already in memory: {existing.content}"
        if existing is not None and existing.status == "proposed":
            return f"Already suggested and waiting for approval: {existing.content}"
        store.retain(fact, source="arqen", provenance="chat", status="proposed", confidence=0.6)
        return (
            f"Suggested for memory, waiting for the user's approval under Memory: {fact}. "
            "Tell the user it was suggested; do not say it was saved."
        )
