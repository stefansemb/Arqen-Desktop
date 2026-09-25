from arqen.core.engine import ConversationEngine
from arqen.core.memory_store import MemoryStore
from arqen.providers.demo import DemoProvider


def _store(tmp_path, *facts, status="approved") -> MemoryStore:
    store = MemoryStore(tmp_path / "memory.json")
    for fact in facts:
        store.retain(fact, status=status)
    return store


def test_recall_finds_inflected_swedish_words(tmp_path):
    store = _store(tmp_path, "Min hund heter Bosse", "Jag bor i Göteborg")
    assert [m.content for m in store.recall("Vad gör hunden idag?")] == ["Min hund heter Bosse"]


def test_recall_ignores_stopwords(tmp_path):
    store = _store(tmp_path, "Min hund heter Bosse", "Min bil är röd")
    # "min" and "vad" alone must not pull in every memory that contains them.
    assert store.recall("vad är min") == []


def test_recall_ranks_by_how_many_words_match(tmp_path):
    store = _store(tmp_path, "Projektet Arqen använder Python", "Arqen Mission Control körs lokalt med Python")
    best = store.recall("Arqen Mission Control python")[0]
    assert best.content == "Arqen Mission Control körs lokalt med Python"


def test_proposed_memories_are_not_presented_as_approved(tmp_path):
    store = _store(tmp_path, "Godkänt faktum")
    store.retain("Föreslaget faktum", status="proposed")
    assert [m.content for m in store.recall()] == ["Godkänt faktum"]
    assert len(store.recall(include_proposed=True)) == 2


def _system(engine: ConversationEngine) -> str:
    systems = [m for m in engine.messages if m.role == "system"]
    assert len(systems) == 1  # refreshed in place, never stacked
    return systems[0].content


def test_small_memory_is_sent_whole(tmp_path):
    store = _store(tmp_path, "Min hund heter Bosse", "Jag bor i Göteborg")
    engine = ConversationEngine(provider=DemoProvider(), memory_store=store)
    engine.respond("hej")
    assert "Min hund heter Bosse" in _system(engine)
    assert "Jag bor i Göteborg" in _system(engine)


def test_large_memory_is_filtered_per_turn(tmp_path):
    facts = [f"Anteckning nummer {index} om trädgården" for index in range(20)]
    store = _store(tmp_path, "Min hund heter Bosse", "Jag bor i Göteborg", *facts)
    engine = ConversationEngine(provider=DemoProvider(), memory_store=store)

    engine.respond("Vad heter hunden?")
    system = _system(engine)
    assert "Min hund heter Bosse" in system
    assert "Jag bor i Göteborg" not in system
    assert "of 22 stored memories" in system

    engine.respond("Var bor jag, i vilken stad? Göteborg?")
    system = _system(engine)
    assert "Jag bor i Göteborg" in system
    assert "Min hund heter Bosse" not in system
