from arqen.mission import Agent, MissionStore


def test_store_lists_agents_by_name(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_agent(Agent("writer", "Writer", "content"))
    store.save_agent(Agent("orchestrator", "Orchestrator", "coordination"))

    assert [agent.id for agent in store.list_agents()] == ["orchestrator", "writer"]
