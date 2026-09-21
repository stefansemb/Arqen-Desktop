from arqen.core.memory_store import MemoryStore


def test_memory_can_be_added_and_removed(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    store.remember("Arqen är viktigt")
    store.remember("Arqen är viktigt")
    assert store.list() == ["Arqen är viktigt"]
    assert store.forget("Arqen är viktigt") is True
    assert store.list() == []

