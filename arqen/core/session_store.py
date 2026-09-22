import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arqen.core.contracts import Message
from arqen.config.paths import data_dir


@dataclass
class ChatSession:
    session_id: str
    title: str = "Ny chatt"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    messages: list[Message] = field(default_factory=list)


class SessionStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or data_dir() / "sessions"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, title: str = "Ny chatt") -> ChatSession:
        return ChatSession(session_id=uuid.uuid4().hex, title=title)

    def save(self, session: ChatSession) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
        path = self.base_dir / f"{session.session_id}.json"
        payload: dict[str, Any] = asdict(session)
        payload["messages"] = [asdict(message) for message in session.messages]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def load(self, session_id: str) -> ChatSession:
        path = self.base_dir / f"{session_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        messages = [Message(**message) for message in payload.get("messages", [])]
        return ChatSession(
            session_id=payload["session_id"],
            title=payload.get("title", "Ny chatt"),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
            messages=messages,
        )

    def list_sessions(self) -> list[ChatSession]:
        sessions = []
        for path in self.base_dir.glob("*.json"):
            try:
                session = self.load(path.stem)
                # Ignore legacy smoke-test chats that used to be created while
                # checking startup and system-status behavior.
                if session.title.strip().casefold() in {"hej arqen", "systemstatus"}:
                    continue
                sessions.append(session)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(sessions, key=lambda session: session.updated_at, reverse=True)

    def delete(self, session_id: str) -> None:
        path = self.base_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
