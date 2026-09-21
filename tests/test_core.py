from arqen.core.engine import ConversationEngine
from arqen.providers.demo import DemoProvider


def test_demo_provider_round_trip() -> None:
    engine = ConversationEngine(DemoProvider())
    assert engine.respond("Hej Arqen") == "Jag tog emot: Hej Arqen"
    assert len(engine.messages) == 3
    assert engine.messages[0].role == "system"


def test_demo_provider_can_request_safe_tool() -> None:
    from arqen.tools.builtins import create_builtin_registry

    engine = ConversationEngine(DemoProvider(), create_builtin_registry())
    result = engine.respond("systemstatus")
    assert "OS:" in result
    assert engine.messages[-1].role == "tool"
