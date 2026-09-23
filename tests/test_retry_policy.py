from arqen.mission import MissionStore, Task


def test_retry_policy_limits_attempts(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Retry", "run")
    store.save_task(task)
    assert store.claim_task(task.id)
    store.update_task(task.id, "failed", "temporary")
    assert store.retry_task(task.id) is True
    assert store.claim_task(task.id)
    store.update_task(task.id, "failed", "temporary")
    assert store.retry_task(task.id) is True
    assert store.claim_task(task.id)
    store.update_task(task.id, "failed", "permanent")
    assert store.retry_task(task.id) is False
