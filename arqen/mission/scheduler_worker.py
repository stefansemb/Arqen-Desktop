from threading import Event, Thread

from arqen.mission.scheduler import MissionScheduler


class SchedulerWorker:
    def __init__(self, scheduler: MissionScheduler, interval: float = 30.0) -> None:
        self.scheduler = scheduler
        self.interval = interval
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="arqen-mission-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval + 1.0))
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.scheduler.poll()
            self._stop.wait(self.interval)
