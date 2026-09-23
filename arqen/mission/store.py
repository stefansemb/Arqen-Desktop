import json
import sqlite3
from pathlib import Path

from arqen.mission.contracts import Agent, Event, Task, TaskStatus


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
                    runtime TEXT NOT NULL, enabled INTEGER NOT NULL
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
            """)

    def save_agent(self, agent: Agent) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO agents VALUES (?, ?, ?, ?, ?)",
                       (agent.id, agent.name, agent.role, agent.runtime, int(agent.enabled)))

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

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(row["id"], row["title"], row["prompt"], row["status"], row["agent_id"], row["created_at"], row["updated_at"], row["error"])
