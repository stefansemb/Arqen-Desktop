from arqen.mission import MissionRunner, MissionStore, Task
from arqen.mission.task_worker import TaskWorker


class Runtime:
    def run(self, prompt):
        return "done"


def test_task_worker_processes_queued_tasks(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Queued", "run")
    store.save_task(task)
    worker = TaskWorker(store, MissionRunner(store, Runtime()), interval=0.01)
    worker.start()
    worker._stop.wait(0.05)
    worker.stop()

    assert store.get_task(task.id).status == "completed"
