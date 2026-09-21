from dataclasses import dataclass
from typing import Any

from arqen.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    output: str
    confirmation_required: bool = False


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._pending: tuple[str, dict[str, Any]] | None = None

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ExecutionResult:
        tool = self.registry.get(name)
        if tool is None:
            return ExecutionResult(False, f"Unknown tool: {name}")
        validation_error = tool.validate_arguments(arguments or {})
        if validation_error:
            return ExecutionResult(False, validation_error)
        if tool.requires_confirmation:
            preflight_error = tool.preflight(arguments or {})
            if preflight_error:
                return ExecutionResult(False, preflight_error)
            self._pending = (name, arguments or {})
            return ExecutionResult(
                False,
                f"User confirmation required for tool: {name}",
                confirmation_required=True,
            )
        try:
            return ExecutionResult(True, tool.run(arguments or {}))
        except Exception as exc:
            return ExecutionResult(False, f"Tool failed: {exc}")

    def confirm_pending(self, accepted: bool) -> ExecutionResult:
        pending, self._pending = self._pending, None
        if pending is None:
            return ExecutionResult(False, "No pending tool request")
        if not accepted:
            return ExecutionResult(False, "Tool request cancelled")
        name, arguments = pending
        tool = self.registry.get(name)
        if tool is None:
            return ExecutionResult(False, f"Unknown tool: {name}")
        try:
            return ExecutionResult(True, tool.run(arguments))
        except Exception as exc:
            return ExecutionResult(False, f"Tool failed: {exc}")
