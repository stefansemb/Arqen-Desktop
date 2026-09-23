import pytest

from arqen.mission import MissionRunner, MissionStore, Workflow, WorkflowRunner, WorkflowStep


class Runtime:
    def run(self, prompt):
        return "ok"


def test_resume_requires_waiting_run(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_workflow(Workflow("w", "W", (WorkflowStep("one", "one"),)))
    with pytest.raises(ValueError, match="kan inte återupptas"):
        WorkflowRunner(store, MissionRunner(store, Runtime())).resume("missing")
