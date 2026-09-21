from abc import ABC, abstractmethod

from arqen.core.contracts import Message, ProviderResponse


class AIProvider(ABC):
    """Provider contract; network and vendor details stay outside the engine."""

    @abstractmethod
    def respond(self, messages: list[Message]) -> ProviderResponse:
        raise NotImplementedError

