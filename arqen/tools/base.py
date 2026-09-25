from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str
    description: str
    requires_confirmation: bool = False
    # Offered to the model on every turn, even when the per-turn selection of
    # relevant tools finds no words in common with the conversation.
    always_offered: bool = False
    # The connection this tool belongs to, if it needs one (e.g. "github").
    connector_id: str | None = None
    arguments_schema: dict[str, type] = {}

    def available(self) -> bool:
        """Whether the tool can run now: its connection is set up and not paused."""
        if self.connector_id is None:
            return True
        from arqen.connectors.external import connector_by_id

        connector = connector_by_id(self.connector_id)
        return connector is not None and connector.is_active()

    def credentials(self) -> dict[str, str]:
        """This tool's connection credentials, read when it runs and never passed to the model."""
        from arqen.connectors.store import load_credentials

        return load_credentials(self.connector_id) if self.connector_id else {}

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
