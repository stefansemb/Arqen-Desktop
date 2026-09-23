from arqen.mission import MissionStore, Workflow, WorkflowRun, WorkflowStep


def test_workflow_definition_round_trips(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    workflow = Workflow("content", "Content pipeline", (WorkflowStep("research", "research", "scout"),))
    store.save_workflow(workflow)
    saved = store.list_workflows()[0]
    assert saved.name == "Content pipeline"
    assert saved.steps[0].agent_id == "scout"

    store.save_workflow_run(WorkflowRun("run-1", "content", "completed", 1, ("done",)))
    assert store.list_workflow_runs("content")[0].status == "completed"
