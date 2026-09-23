from arqen.mission import MissionRunner, MissionStore, WorkflowRunner, WorkflowStep


class Runtime:
    def run(self, prompt):
        return f"result:{prompt}"


def test_workflow_passes_previous_result_between_steps(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    results = WorkflowRunner(store, MissionRunner(store, Runtime())).run(
        "Pipeline", [WorkflowStep("research", "research"), WorkflowStep("write", "write {{previous}}")]
    )
    assert results == ["result:research", "result:write result:research"]


def test_workflow_injects_input_into_first_step(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    results = WorkflowRunner(store, MissionRunner(store, Runtime())).run(
        "Pipeline", [WorkflowStep("research", "research {{input}}")], input_text="Topic: AI agents"
    )
    assert results == ["result:research Topic: AI agents"]
