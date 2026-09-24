from arqen.core.memory_store import MemoryStore


def test_memory_can_be_added_and_removed(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    store.remember("Arqen är viktigt")
    store.remember("Arqen är viktigt")
    assert store.list() == ["Arqen är viktigt"]
    assert store.forget("Arqen är viktigt") is True
    assert store.list() == []


def test_memory_retain_recall_and_reflect_metadata(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    store.retain("Användaren föredrar svenska", source="chat", provenance="task-1", confidence=0.8)
    store.retain("Gammal uppgift", status="obsolete")
    records = store.recall("svenska")
    assert len(records) == 1
    assert records[0].source == "chat"
    assert records[0].confidence == 0.8
    assert store.reflect() == {"total": 2, "approved": 1, "proposed": 0, "obsolete": 1}
