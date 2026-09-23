from collections.abc import Callable

from arqen.core.engine import ConversationEngine
from arqen.mission.contracts import Event, Task
from arqen.mission.store import MissionStore


class MissionRunner:
    """Execute one stored task through an Arqen conversation engine."""

    def __init__(self, store: MissionStore, engine_factory: Callable[[], ConversationEngine]) -> None:
        self.store = store
        self.engine_factory = engine_factory

    def run(self, task_id: str) -> str:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown mission task: {task_id}")
        if task.status not in {"queued", "failed"}:
            raise ValueError(f"Task cannot be run from status '{task.status}'")

        self.store.update_task(task.id, "running")
        self._event(task, "started", "Task started")
        try:
            result = self.engine_factory().respond(task.prompt)
        except Exception as exc:
            self.store.update_task(task.id, "failed", str(exc))
            self._event(task, "failed", str(exc))
            raise
        self.store.update_task(task.id, "completed")
        self._event(task, "completed", "Task completed")
        return result

    def _event(self, task: Task, kind: str, message: str) -> None:
        self.store.add_event(Event.create(task.id, kind, message))
