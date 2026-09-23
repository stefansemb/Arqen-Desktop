from arqen.mission import Agent, MissionStore
from arqen.config.settings import load_mission_runtime_config


def test_store_lists_agents_by_name(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_agent(Agent("writer", "Writer", "content", allowed_tools=("current_time",)))
    store.save_agent(Agent("orchestrator", "Orchestrator", "coordination"))

    assert [agent.id for agent in store.list_agents()] == ["orchestrator", "writer"]
    assert store.get_agent("writer").allowed_tools == ("current_time",)


def test_missing_mission_runtime_config_is_safe(tmp_path):
    assert load_mission_runtime_config(tmp_path / "missing.json") == {}
