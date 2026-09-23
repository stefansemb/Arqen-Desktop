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
            self.store.recover_stale_tasks(3600)
            for task in self.store.list_tasks("queued"):
                if self._stop.is_set():
                    break
                try:
                    self.runner.run(task.id)
                except Exception:
                    # MissionRunner persists the failure; one bad task must
                    # not stop the worker from processing the queue.
                    continue
            self._stop.wait(self.interval)
