from arqen.mission import MissionStore, Task


def test_task_claim_is_atomic(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("One", "run")
    store.save_task(task)

    assert store.claim_task(task.id) is True
    assert store.claim_task(task.id) is False
    assert store.get_task(task.id).status == "running"
