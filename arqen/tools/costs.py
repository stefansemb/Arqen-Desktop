"""What a tool call cost, reported by the tool and logged by the gateway.

A tool that spends money calls ``report_cost`` with the service's own figure
(never an estimate).  The gateway collects the reports made while it runs a
tool and writes their sum to the audit log.  Outside a gateway call the
report goes nowhere, so tools can report unconditionally.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_bucket: ContextVar[list[float] | None] = ContextVar("arqen_tool_costs", default=None)


def report_cost(usd) -> None:
    """Record ``usd`` for the current tool call; ignored if it is not a number."""
    bucket = _bucket.get()
    if bucket is None:
        return
    try:
        amount = float(usd)
    except (TypeError, ValueError):
        return
    if amount >= 0:
        bucket.append(amount)


@contextmanager
def collecting() -> Iterator[list[float]]:
    """Collect the costs reported inside the block."""
    bucket: list[float] = []
    token = _bucket.set(bucket)
    try:
        yield bucket
    finally:
        _bucket.reset(token)
