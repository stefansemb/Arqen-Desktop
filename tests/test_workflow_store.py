from arqen.mission import MissionStore, Workflow, WorkflowStep


def test_workflow_definition_round_trips(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    workflow = Workflow("content", "Content pipeline", (WorkflowStep("research", "research", "scout"),))
    store.save_workflow(workflow)
    saved = store.list_workflows()[0]
    assert saved.name == "Content pipeline"
    assert saved.steps[0].agent_id == "scout"
