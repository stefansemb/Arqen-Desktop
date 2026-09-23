from arqen.mission.scheduler_worker import SchedulerWorker


class Scheduler:
    def __init__(self):
        self.calls = 0

    def poll(self):
        self.calls += 1


def test_scheduler_worker_starts_and_stops(tmp_path):
    scheduler = Scheduler()
    worker = SchedulerWorker(scheduler, interval=0.01)
    worker.start()
    worker._stop.wait(0.05)
    worker.stop()
    assert scheduler.calls >= 1
