from collections.abc import Callable

from arqen.mission.contracts import Approval, Event, Task
from arqen.mission.runtime import AgentRuntime, ApprovalRequired, ArqenRuntime
from arqen.mission.store import MissionStore


class MissionRunner:
    """Execute one stored task through an Arqen conversation engine."""

    def __init__(self, store: MissionStore, engine_factory: Callable[[], object] | AgentRuntime,
                 runtimes: dict[str, AgentRuntime] | None = None) -> None:
        self.store = store
        self.runtime = engine_factory if hasattr(engine_factory, "run") else ArqenRuntime(engine_factory)
        self.runtimes = runtimes or {}

    def run(self, task_id: str) -> str:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown mission task: {task_id}")
        if task.status not in {"queued", "failed"}:
            raise ValueError(f"Task cannot be run from status '{task.status}'")
        if task.status == "queued" and not self.store.claim_task(task.id):
            raise ValueError(f"Task '{task.id}' kunde inte claimas.")
        runtime = self._runtime_for(task)

        if task.status == "failed":
            self.store.update_task(task.id, "running")
        self._event(task, "started", "Task started")
        try:
            if isinstance(runtime, ArqenRuntime):
                agent = self.store.get_agent(task.agent_id) if task.agent_id else None
                try:
                    # An agent's list is its whole allowance, even when empty;
                    # only a task without an agent runs with every tool.
                    result = runtime.run(task.prompt, agent.allowed_tools if agent else None,
                                         agent.approval_tools if agent else None,
                                         lambda action, payload: (_ for _ in ()).throw(ApprovalRequired(action, payload)))
                except ApprovalRequired as approval:
                    self.request_approval(task.id, approval.action, approval.payload)
                    return "Task väntar på godkännande."
            else:
                result = runtime.run(task.prompt)
        except Exception as exc:
            self.store.update_task(task.id, "failed", str(exc))
            self._event(task, "failed", str(exc))
            raise
        current = self.store.get_task(task.id)
        if current is None or current.status != "running":
            return result
        self.store.update_task(task.id, "completed", result=result)
        self._event(task, "completed", "Task completed")
        return result

    def request_approval(self, task_id: str, action: str, payload: dict) -> Approval:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown mission task: {task_id}")
        if task.status not in {"queued", "running"}:
            raise ValueError(f"Task cannot request approval from status '{task.status}'")
        approval = Approval(__import__("uuid").uuid4().hex, task_id, action, payload)
        self.store.save_approval(approval)
        self.store.update_task(task_id, "waiting_approval")
        self._event(task, "approval_requested", action)
        return approval

    def resume(self, task_id: str) -> str:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown mission task: {task_id}")
        approvals = [item for item in self.store.list_approvals() if item.task_id == task_id]
        if task.status != "waiting_approval" or not approvals:
            raise ValueError("Task väntar inte på ett approval.")
        latest = approvals[0]
        if latest.status == "rejected":
            self.store.update_task(task_id, "cancelled")
            self._event(task, "approval_rejected", latest.action)
            return "Task avbruten efter avslaget."
        if latest.status != "approved":
            raise ValueError("Approval väntar fortfarande på beslut.")
        self._event(task, "approval_approved", latest.action)
        self.store.update_task(task_id, "queued")
        return self.run(task_id)

    def _event(self, task: Task, kind: str, message: str) -> None:
        self.store.add_event(Event.create(task.id, kind, message))

    def _runtime_for(self, task: Task) -> AgentRuntime:
        if not task.agent_id:
            return self.runtime
        agent = self.store.get_agent(task.agent_id)
        if agent is None:
            raise ValueError(f"Agenten '{task.agent_id}' finns inte.")
        if not agent.enabled:
            raise ValueError(f"Agenten '{agent.name}' är inaktiv.")
        runtime = self.runtimes.get(agent.id)
        if runtime is None and agent.runtime == "arqen":
            runtime = self.runtime
        if runtime is None:
            raise ValueError(f"Ingen runtime är konfigurerad för agenten '{agent.name}'.")
        return runtime

    def runtime_status(self, agent_id: str) -> dict[str, object]:
        agent = self.store.get_agent(agent_id)
        if agent is None:
            raise KeyError(f"Unknown mission agent: {agent_id}")
        configured = agent_id in self.runtimes or agent.runtime == "arqen"
        runtime = self.runtimes.get(agent_id)
        if runtime is not None and hasattr(runtime, "health"):
            health = runtime.health()
            return {"agent_id": agent.id, "name": agent.name, "runtime": agent.runtime,
                    "enabled": agent.enabled, "configured": configured, **health}
        return {
            "agent_id": agent.id,
            "name": agent.name,
            "runtime": agent.runtime,
            "enabled": agent.enabled,
            "configured": configured,
            "status": "ready" if agent.enabled and configured else "offline",
        }
