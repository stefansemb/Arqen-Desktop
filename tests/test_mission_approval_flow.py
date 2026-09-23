import pytest

from arqen.mission import MissionRunner, MissionStore, Task


class Runtime:
    def run(self, prompt):
        return "klart"


def test_task_can_pause_and_resume_after_approval(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Publish", "publicera")
    store.save_task(task)
    runner = MissionRunner(store, Runtime())

    approval = runner.request_approval(task.id, "publish", {"channel": "youtube"})
    assert store.get_task(task.id).status == "waiting_approval"
    store.decide_approval(approval.id, "approved")
    assert runner.resume(task.id) == "klart"
    assert store.get_task(task.id).status == "completed"


def test_rejected_approval_cancels_task(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Publish", "publicera")
    store.save_task(task)
    runner = MissionRunner(store, Runtime())
    approval = runner.request_approval(task.id, "publish", {})
    store.decide_approval(approval.id, "rejected")

    assert runner.resume(task.id) == "Task avbruten efter avslaget."
    assert store.get_task(task.id).status == "cancelled"


def test_cannot_resume_pending_approval(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Publish", "publicera")
    store.save_task(task)
    runner = MissionRunner(store, Runtime())
    runner.request_approval(task.id, "publish", {})

    with pytest.raises(ValueError, match="väntar fortfarande"):
        runner.resume(task.id)
