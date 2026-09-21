from typing import Any

from arqen.tools.base import Tool
from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry


class ConfirmationProbe(Tool):
    name = "confirmation_probe"
    description = "Test-only tool that records whether confirmation was granted."
    requires_confirmation = True

    def __init__(self) -> None:
        self.runs = 0

    def run(self, arguments: dict[str, Any]) -> str:
        self.runs += 1
        return "confirmed action executed"


def make_executor() -> tuple[ToolExecutor, ConfirmationProbe]:
    probe = ConfirmationProbe()
    registry = ToolRegistry()
    registry.register(probe)
    return ToolExecutor(registry), probe


def test_confirmation_blocks_execution_until_accepted() -> None:
    executor, probe = make_executor()
    pending = executor.execute("confirmation_probe")
    assert pending.confirmation_required is True
    assert probe.runs == 0

    completed = executor.confirm_pending(True)
    assert completed.ok is True
    assert probe.runs == 1


def test_rejected_confirmation_does_not_execute() -> None:
    executor, probe = make_executor()
    executor.execute("confirmation_probe")
    cancelled = executor.confirm_pending(False)
    assert cancelled.ok is False
    assert "cancelled" in cancelled.output.lower()
    assert probe.runs == 0

