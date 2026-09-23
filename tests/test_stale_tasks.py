from arqen.mission import MissionStore, Task


def test_store_recovers_stale_running_task(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Stuck", "run")
    store.save_task(task)
    assert store.claim_task(task.id)

    recovered = store.recover_stale_tasks(60, "2099-09-23T10:00:00+00:00")
    assert recovered == 1
    saved = store.get_task(task.id)
    assert saved.status == "failed"
    assert "timeout" in saved.error
