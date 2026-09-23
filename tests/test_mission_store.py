from arqen.mission import Event, MissionStore, Task


def test_store_round_trips_tasks_and_events(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Research", "Find three relevant sources")
    store.save_task(task)
    store.add_event(Event.create(task.id, "created", "Task created"))
    store.update_task(task.id, "running")

    saved = store.get_task(task.id)
    assert saved is not None
    assert saved.status == "running"
    assert [event.kind for event in store.list_events(task.id)] == ["created"]


def test_store_filters_tasks_by_status(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    queued = Task.create("Queued", "one")
    done = Task.create("Done", "two")
    store.save_task(queued)
    store.save_task(done)
    store.update_task(done.id, "completed")

    assert [task.id for task in store.list_tasks("queued")] == [queued.id]
    assert [task.id for task in store.list_tasks("completed")] == [done.id]
