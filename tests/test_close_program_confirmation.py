import os

import pytest

pytest.importorskip("psutil")

from arqen.tools.close_program import CloseProgramTool
from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry


def _executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(CloseProgramTool())
    return ToolExecutor(registry)


def test_closing_a_program_waits_for_confirmation():
    executor = _executor()
    # The test's own process: it exists, and is never confirmed, so never ended.
    result = executor.execute("close_program", {"target": str(os.getpid())})
    assert result.confirmation_required
    assert executor._pending == ("close_program", {"target": str(os.getpid())})


def test_missing_process_is_reported_without_asking():
    executor = _executor()
    result = executor.execute("close_program", {"target": "no-such-process-arqen-test"})
    assert not result.confirmation_required
    assert "not found" in result.output
    assert executor._pending is None
