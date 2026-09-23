import pytest

from arqen.mission import MissionRunner, MissionStore, Task


class FakeEngine:
    def __init__(self, result="klart", error=None):
        self.result = result
        self.error = error
        self.prompts = []

    def respond(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


def test_runner_executes_and_records_lifecycle(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Test", "Gör jobbet")
    store.save_task(task)
    engine = FakeEngine("färdigt")

    result = MissionRunner(store, lambda: engine).run(task.id)

    assert result == "färdigt"
    assert store.get_task(task.id).status == "completed"
    assert [event.kind for event in store.list_events(task.id)] == ["started", "completed"]


def test_runner_marks_provider_errors_as_failed(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Test", "Gör jobbet")
    store.save_task(task)
    error = RuntimeError("provider nere")

    with pytest.raises(RuntimeError, match="provider nere"):
        MissionRunner(store, lambda: FakeEngine(error=error)).run(task.id)

    saved = store.get_task(task.id)
    assert saved.status == "failed"
    assert saved.error == "provider nere"
    assert [event.kind for event in store.list_events(task.id)] == ["started", "failed"]


def test_runner_accepts_a_runtime_adapter(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    task = Task.create("Test", "Gör jobbet")
    store.save_task(task)

    class Runtime:
        def run(self, prompt):
            return f"runtime: {prompt}"

    assert MissionRunner(store, Runtime()).run(task.id) == "runtime: Gör jobbet"
