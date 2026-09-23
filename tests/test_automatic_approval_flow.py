from arqen.mission import Agent, MissionRunner, MissionStore, Task


class ConfirmationEngine:
    def __init__(self):
        self.on_confirmation_required = None
        self.calls = 0

    def respond(self, prompt):
        self.calls += 1
        if self.calls == 1:
            self.on_confirmation_required("publish", {"channel": "youtube"})
        return "publicerat"


def test_engine_confirmation_pauses_and_resume_completes(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_agent(Agent("publisher", "Publisher", "publishing", runtime="arqen"))
    task = Task.create("Publish", "publicera videon", agent_id="publisher")
    store.save_task(task)
    engine = ConfirmationEngine()
    runner = MissionRunner(store, lambda: engine)

    assert runner.run(task.id) == "Task väntar på godkännande."
    assert store.get_task(task.id).status == "waiting_approval"
    approval = store.list_approvals()[0]
    assert approval.action == "publish"

    store.decide_approval(approval.id, "approved")
    assert runner.resume(task.id) == "publicerat"
    assert store.get_task(task.id).status == "completed"
