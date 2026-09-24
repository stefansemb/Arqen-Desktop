from threading import Event, Thread

from arqen.mission.runner import MissionRunner
from arqen.mission.store import MissionStore


class TaskWorker:
    def __init__(self, store: MissionStore, runner: MissionRunner, interval: float = 1.0) -> None:
        self.store = store
        self.runner = runner
        self.interval = interval
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="arqen-mission-task-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval + 1.0))
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            # A provider call should not keep a task active indefinitely.
            # Fifteen minutes leaves room for real research while recovering
            # hung desktop/model sessions promptly.
            self.store.recover_stale_tasks(900)
            for task in self.store.list_tasks("queued"):
                if self._stop.is_set():
                    break
                self._run_with_timeout(task.id, 900.0)
            self._stop.wait(self.interval)

    def _run_with_timeout(self, task_id: str, timeout: float) -> None:
        outcome: dict[str, BaseException | None] = {"error": None}

        def execute() -> None:
            try:
                self.runner.run(task_id)
            except BaseException as exc:
                outcome["error"] = exc

        thread = Thread(target=execute, name=f"arqen-task-{task_id[:8]}", daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.store.update_task(task_id, "failed", "Task timed out after 15 minutes.")
