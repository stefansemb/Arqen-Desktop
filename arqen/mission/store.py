import json
import sqlite3
from pathlib import Path

from arqen.mission.contracts import Agent, Approval, Event, Task, TaskStatus


class MissionStore:
    """Small, local-first store for Mission Control state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    runtime TEXT NOT NULL, enabled INTEGER NOT NULL, allowed_tools TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
                    status TEXT NOT NULL, agent_id TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                    message TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(agents)").fetchall()}
            if "allowed_tools" not in columns:
                db.execute("ALTER TABLE agents ADD COLUMN allowed_tools TEXT NOT NULL DEFAULT '[]'")

    def save_agent(self, agent: Agent) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO agents VALUES (?, ?, ?, ?, ?, ?)",
                       (agent.id, agent.name, agent.role, agent.runtime, int(agent.enabled), json.dumps(agent.allowed_tools)))

    def get_agent(self, agent_id: str) -> Agent | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return self._agent(row) if row else None

    def list_agents(self) -> list[Agent]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM agents ORDER BY name").fetchall()
        return [self._agent(row) for row in rows]

    def save_task(self, task: Task) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (task.id, task.title, task.prompt, task.status, task.agent_id,
                        task.created_at, task.updated_at, task.error))

    def get_task(self, task_id: str) -> Task | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task(row) if row else None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        query = "SELECT * FROM tasks"
        params: tuple[str, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at DESC"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._task(row) for row in rows]

    def update_task(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        from arqen.mission.contracts import now
        with self._connect() as db:
            db.execute("UPDATE tasks SET status = ?, updated_at = ?, error = ? WHERE id = ?",
                       (status, now(), error, task_id))

    def add_event(self, event: Event) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                       (event.id, event.task_id, event.kind, event.message,
                        event.created_at, json.dumps(event.payload)))

    def list_events(self, task_id: str) -> list[Event]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM events WHERE task_id = ? ORDER BY created_at", (task_id,)).fetchall()
        return [Event(row["id"], row["task_id"], row["kind"], row["message"], row["created_at"], json.loads(row["payload"])) for row in rows]

    def save_approval(self, approval: Approval) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO approvals VALUES (?, ?, ?, ?, ?, ?)",
                       (approval.id, approval.task_id, approval.action,
                        json.dumps(approval.payload), approval.status, approval.created_at))

    def get_approval(self, approval_id: str) -> Approval | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return self._approval(row) if row else None

    def list_approvals(self, status: str | None = None) -> list[Approval]:
        query = "SELECT * FROM approvals"
        params: tuple[str, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at DESC"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._approval(row) for row in rows]

    def decide_approval(self, approval_id: str, status: str) -> None:
        if status not in {"approved", "rejected"}:
            raise ValueError("Approval måste godkännas eller avslås.")
        with self._connect() as db:
            db.execute("UPDATE approvals SET status = ? WHERE id = ?", (status, approval_id))

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(row["id"], row["title"], row["prompt"], row["status"], row["agent_id"], row["created_at"], row["updated_at"], row["error"])

    @staticmethod
    def _agent(row: sqlite3.Row) -> Agent:
        return Agent(row["id"], row["name"], row["role"], row["runtime"], bool(row["enabled"]), tuple(json.loads(row["allowed_tools"])))

    @staticmethod
    def _approval(row: sqlite3.Row) -> Approval:
        return Approval(row["id"], row["task_id"], row["action"], json.loads(row["payload"]), row["status"], row["created_at"])
