from __future__ import annotations

from dataclasses import dataclass
import json
from uuid import uuid4
from typing import TYPE_CHECKING

from arqen.mission.contracts import Task
if TYPE_CHECKING:
    from arqen.mission.runner import MissionRunner


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    prompt: str
    agent_id: str | None = None


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str
    steps: tuple[WorkflowStep, ...]
    enabled: bool = True


@dataclass(frozen=True)
class WorkflowRun:
    id: str
    workflow_id: str
    status: str = "queued"
    current_step: int = 0
    results: tuple[str, ...] = ()


class WorkflowRunner:
    def __init__(self, store: MissionStore, runner: MissionRunner) -> None:
        self.store = store
        self.runner = runner

    def save(self, workflow: Workflow) -> None:
        self.store.save_workflow(workflow)

    def run(self, name: str, steps: list[WorkflowStep], workflow_id: str | None = None, input_text: str = "") -> list[str]:
        run = WorkflowRun(uuid4().hex, workflow_id or name, "running")
        self.store.save_workflow_run(run)
        results: list[str] = []
        previous = ""
        for index, step in enumerate(steps):
            prompt = step.prompt.replace("{{previous}}", previous).replace("{{input}}", input_text)
            if index == 0 and input_text and "{{input}}" not in step.prompt:
                prompt = f"Workflow input:\n{input_text}\n\n{prompt}"
            task = Task(uuid4().hex, f"{name}: {step.name}", prompt, agent_id=step.agent_id)
            self.store.save_task(task)
            result = self.runner.run(task.id)
            results.append(result)
            previous = result
            saved_run = WorkflowRun(run.id, run.workflow_id, "running", len(results), tuple(results))
            saved = self.store.get_task(task.id)
            if saved.status != "completed":
                self.store.save_workflow_run(WorkflowRun(run.id, run.workflow_id, "waiting_approval" if saved.status == "waiting_approval" else "failed", len(results), tuple(results)))
                break
            self.store.save_workflow_run(saved_run)
        else:
            self.store.save_workflow_run(WorkflowRun(run.id, run.workflow_id, "completed", len(results), tuple(results)))
        return results

    def resume(self, run_id: str) -> list[str]:
        run = self.store.get_workflow_run(run_id)
        if run is None or run.status != "waiting_approval":
            raise ValueError("Workflow-run kan inte återupptas.")
        workflow = self.store.get_workflow(run.workflow_id)
        if workflow is None:
            raise ValueError("Workflow-definitionen saknas.")
        previous = run.results[-1] if run.results else ""
        results = list(run.results)
        for step in workflow.steps[run.current_step:]:
            task = Task(uuid4().hex, f"{workflow.name}: {step.name}", step.prompt.replace("{{previous}}", previous), agent_id=step.agent_id)
            self.store.save_task(task)
            result = self.runner.run(task.id)
            results.append(result)
            previous = result
            saved = self.store.get_task(task.id)
            status = "waiting_approval" if saved.status == "waiting_approval" else "failed" if saved.status != "completed" else "running"
            self.store.save_workflow_run(WorkflowRun(run.id, run.workflow_id, status, len(results), tuple(results)))
            if saved.status != "completed":
                return results
        self.store.save_workflow_run(WorkflowRun(run.id, run.workflow_id, "completed", len(results), tuple(results)))
        return results
