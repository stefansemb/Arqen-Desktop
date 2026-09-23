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

    def run(self, prompt: str, allowed_tools: tuple[str, ...] | None = None) -> str:
        engine = self.engine_factory()
        if allowed_tools:
            engine.tools._tools = {name: tool for name, tool in engine.tools._tools.items() if name in allowed_tools}
        return engine.respond(prompt)


class HermesRuntime:
    """Small subprocess adapter for a locally installed Hermes CLI.

    It is deliberately opt-in: callers must provide the executable path. The
    prompt is passed as one argument and no shell is involved.
    """

    def __init__(self, executable: str, working_dir: Path | str | None = None, timeout: float = 300.0,
                 health_args: tuple[str, ...] = ("--version",)) -> None:
        if not executable.strip():
            raise ValueError("Hermes executable måste anges.")
        self.executable = executable
        self.working_dir = str(working_dir) if working_dir else None
        self.timeout = timeout
        self.health_args = health_args

    def health(self) -> dict[str, str]:
        try:
            completed = subprocess.run(
                [self.executable, *self.health_args], cwd=self.working_dir,
                capture_output=True, text=True, timeout=min(self.timeout, 15),
                check=False, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "offline", "detail": str(exc)}
        if completed.returncode != 0:
            return {"status": "error", "detail": (completed.stderr or completed.stdout or "okänt fel").strip()}
        return {"status": "ready", "detail": (completed.stdout or completed.stderr or "ok").strip()}

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
