from arqen.mission import Agent, MissionRunner, MissionStore


class Runtime:
    def run(self, prompt):
        return prompt


def test_runtime_status_reports_unconfigured_agent(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_agent(Agent("research", "Research", "research"))

    status = MissionRunner(store, Runtime()).runtime_status("research")

    assert status["status"] == "offline"
    assert status["configured"] is False


def test_runtime_status_reports_ready_agent(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_agent(Agent("research", "Research", "research"))

    status = MissionRunner(store, Runtime(), {"research": Runtime()}).runtime_status("research")

    assert status["status"] == "ready"
    assert status["configured"] is True


def test_arqen_agent_uses_default_runtime(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_agent(Agent("writer", "Writer", "content", runtime="arqen"))
    from arqen.mission import Task
    task = Task.create("Write", "skriv", agent_id="writer")
    store.save_task(task)

    assert MissionRunner(store, Runtime()).run(task.id) == "skriv"
