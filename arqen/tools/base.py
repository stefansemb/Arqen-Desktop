from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str
    description: str
    requires_confirmation: bool = False
    arguments_schema: dict[str, type] = {}

    def normalize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments

    def validate_arguments(self, arguments: dict[str, Any]) -> str | None:
        for name, expected_type in self.arguments_schema.items():
            if name not in arguments:
                return f"Missing required argument: {name}"
            if not isinstance(arguments[name], expected_type):
                return f"Invalid argument type for {name}: expected {expected_type.__name__}"
        return None

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        """Optional read-only check before a confirmation request is shown."""
        return None

    @abstractmethod
    def run(self, arguments: dict[str, Any]) -> str:
        raise NotImplementedError
