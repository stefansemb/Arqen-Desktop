"""Local policy and audit gateway for tool executions.

The gateway is deliberately small and dependency-free. It provides the
security boundary that future agent runtimes can share without exposing
secrets or coupling policy to individual tools.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arqen.tools.costs import collecting
from arqen.tools.executor import ExecutionResult, ToolExecutor
from arqen.config import paths


@dataclass(frozen=True)
class ToolPolicy:
    allowed_tools: frozenset[str] | None = None
    denied_tools: frozenset[str] = frozenset()


class ToolGateway:
    def __init__(self, executor: ToolExecutor, audit_path: Path | None = None) -> None:
        self.executor = executor
        self.audit_path = audit_path or paths.data_dir() / "tool-audit.jsonl"
        self.policies: dict[str, ToolPolicy] = {}

    def set_policy(self, agent: str, policy: ToolPolicy) -> None:
        self.policies[agent] = policy

    def catalog(self) -> list[dict[str, Any]]:
        """Return the safe, UI-facing tool catalogue without implementations."""
        return [
            {
                "name": item["name"],
                "description": item["description"],
                "risk": self.risk(item["name"]),
                "requires_confirmation": item["requires_confirmation"],
            }
            for item in self.executor.registry.describe()
        ]

    def policy_view(self) -> list[dict[str, Any]]:
        return [
            {
                "agent": agent,
                "allowed_tools": sorted(policy.allowed_tools) if policy.allowed_tools is not None else None,
                "denied_tools": sorted(policy.denied_tools),
            }
            for agent, policy in sorted(self.policies.items())
        ]

    def audit_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(line) for line in lines if line.strip()]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def risk(self, tool_name: str) -> str:
        tool = self.executor.registry.get(tool_name)
        if tool is None:
            return "unknown"
        return "high" if tool.requires_confirmation else "low"

    def permits(self, tool_name: str, agent: str = "default") -> bool:
        """Whether ``agent``'s policy lets ``tool_name`` run."""
        policy = self.policies.get(agent, ToolPolicy())
        if tool_name in policy.denied_tools:
            return False
        return policy.allowed_tools is None or tool_name in policy.allowed_tools

    def execute(self, tool_name: str, arguments: dict[str, Any] | None = None,
                *, user: str = "local", agent: str = "default") -> ExecutionResult:
        denied = not self.permits(tool_name, agent)
        costs: list[float] = []
        if denied:
            result = ExecutionResult(False, f"Tool denied by policy: {tool_name}")
        else:
            with collecting() as costs:
                result = self._redacted(self.executor.execute(tool_name, arguments))
        self._audit(user, agent, tool_name, result, costs)
        return result

    @staticmethod
    def _redacted(result: ExecutionResult) -> ExecutionResult:
        """Strip every stored key from anything a tool sends back.

        Tools read their keys at run time and never receive them as arguments,
        but an error, an echoed URL or a file could still carry one to the
        model -- connection tokens and model-provider keys alike.
        """
        from arqen.config.secrets import scrub

        output = scrub(result.output)
        return result if output == result.output else ExecutionResult(result.ok, output, result.confirmation_required)

    def _audit(self, user: str, agent: str, tool_name: str, result: ExecutionResult,
               costs: list[float] | None = None) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "user": user,
            "agent": agent,
            "tool": tool_name,
            "risk": self.risk(tool_name),
            "time": datetime.now(timezone.utc).isoformat(),
            "status": "ok" if result.ok else ("approval" if result.confirmation_required else "failed"),
        }
        if costs:
            # The services' own figures in USD; absent when the call cost nothing known.
            entry["cost_usd"] = round(sum(costs), 6)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def confirm_pending(self, accepted: bool, *, user: str = "local", agent: str = "default") -> ExecutionResult:
        pending = self.executor._pending
        with collecting() as costs:
            result = self._redacted(self.executor.confirm_pending(accepted))
        if pending is not None:
            self._audit(user, agent, pending[0], result, costs)
        return result
