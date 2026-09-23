from collections.abc import Callable
from typing import Protocol

from arqen.core.engine import ConversationEngine


class AgentRuntime(Protocol):
    """Execution boundary used by MissionRunner."""

    def run(self, prompt: str) -> str:
        ...


class ArqenRuntime:
    """Runs a mission through an Arqen ConversationEngine."""

    def __init__(self, engine_factory: Callable[[], ConversationEngine]) -> None:
        self.engine_factory = engine_factory

    def run(self, prompt: str) -> str:
        return self.engine_factory().respond(prompt)
