from collections.abc import Callable
import subprocess
from pathlib import Path
from typing import Protocol

from arqen.config import paths
from arqen.core.engine import ConversationEngine
from arqen.core.session_store import SessionStore
from arqen.tools.gateway import ToolPolicy


class ApprovalRequired(RuntimeError):
    def __init__(self, action: str, payload: dict) -> None:
        super().__init__(f"Approval required for {action}")
        self.action = action
        self.payload = payload


class AgentRuntime(Protocol):
    """Execution boundary used by MissionRunner."""

    def run(self, prompt: str) -> str:
        ...


class ArqenRuntime:
    """Runs a mission through an Arqen ConversationEngine."""

    def __init__(self, engine_factory: Callable[[], ConversationEngine]) -> None:
        self.engine_factory = engine_factory

    def run(self, prompt: str, allowed_tools: tuple[str, ...] | None = None,
            approval_tools: tuple[str, ...] | None = None,
            on_approval: Callable[[str, dict], None] | None = None) -> str:
        engine = self.engine_factory()
        if isinstance(engine, ConversationEngine):
            # A task run is not a chat: its transcript is kept, but apart from
            # the user's conversations so it never shows up in the chat list.
            engine.session_store = SessionStore(paths.data_dir() / "mission-sessions")
            engine.new_session()
        # The limits below change the engine itself, so the factory must hand
        # out a fresh engine per task and never the one the user chats with.
        if allowed_tools:
            engine.tools._tools = {name: tool for name, tool in engine.tools._tools.items() if name in allowed_tools}
            # Keep the policy boundary active even for direct/internal tool
            # requests that bypass the model's reduced schema catalogue.
            engine.gateway.set_policy("default", ToolPolicy(allowed_tools=frozenset(allowed_tools)))
        if hasattr(engine, "executor"):
            engine.executor.forced_confirmation = set(approval_tools or ())
        if on_approval is not None:
            engine.on_confirmation_required = on_approval
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
