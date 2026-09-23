from collections.abc import Callable
import subprocess
from pathlib import Path
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


class HermesRuntime:
    """Small subprocess adapter for a locally installed Hermes CLI.

    It is deliberately opt-in: callers must provide the executable path. The
    prompt is passed as one argument and no shell is involved.
    """

    def __init__(self, executable: str, working_dir: Path | str | None = None, timeout: float = 300.0) -> None:
        if not executable.strip():
            raise ValueError("Hermes executable måste anges.")
        self.executable = executable
        self.working_dir = str(working_dir) if working_dir else None
        self.timeout = timeout

    def run(self, prompt: str) -> str:
        try:
            completed = subprocess.run(
                [self.executable, prompt],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Hermes körning överskred timeout.") from exc
        except OSError as exc:
            raise RuntimeError(f"Hermes kunde inte startas: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "okänt fel").strip()
            raise RuntimeError(f"Hermes misslyckades ({completed.returncode}): {detail}")
        return completed.stdout.strip()
