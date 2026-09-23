from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


TaskStatus = Literal["queued", "running", "waiting_approval", "completed", "failed", "cancelled"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    role: str
    runtime: str = "arqen"
    enabled: bool = True
    allowed_tools: tuple[str, ...] = ()
    approval_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    prompt: str
    status: TaskStatus = "queued"
    agent_id: str | None = None
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    error: str | None = None
    claimed_at: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    schedule_id: str | None = None

    @classmethod
    def create(cls, title: str, prompt: str, agent_id: str | None = None) -> "Task":
        return cls(uuid4().hex, title, prompt, agent_id=agent_id)


@dataclass(frozen=True)
class Event:
    id: str
    task_id: str
    kind: str
    message: str
    created_at: str = field(default_factory=now)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, task_id: str, kind: str, message: str, payload: dict[str, Any] | None = None) -> "Event":
        return cls(uuid4().hex, task_id, kind, message, payload=payload or {})


@dataclass(frozen=True)
class Approval:
    id: str
    task_id: str
    action: str
    payload: dict[str, Any]
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: str = field(default_factory=now)


@dataclass(frozen=True)
class Artifact:
    id: str
    task_id: str
    name: str
    path: str
    created_at: str = field(default_factory=now)


@dataclass(frozen=True)
class Schedule:
    id: str
    name: str
    prompt: str
    agent_id: str | None = None
    cron: str | None = None
    run_at: str | None = None
    enabled: bool = True
    created_at: str = field(default_factory=now)
    last_run_at: str | None = None
