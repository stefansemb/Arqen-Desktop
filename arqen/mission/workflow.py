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


class WorkflowRunner:
    def __init__(self, store: MissionStore, runner: MissionRunner) -> None:
        self.store = store
        self.runner = runner

    def save(self, workflow: Workflow) -> None:
        self.store.save_workflow(workflow)

    def run(self, name: str, steps: list[WorkflowStep]) -> list[str]:
        results: list[str] = []
        previous = ""
        for step in steps:
            prompt = step.prompt.replace("{{previous}}", previous)
            task = Task(uuid4().hex, f"{name}: {step.name}", prompt, agent_id=step.agent_id)
            self.store.save_task(task)
            result = self.runner.run(task.id)
            results.append(result)
            previous = result
            saved = self.store.get_task(task.id)
            if saved.status != "completed":
                break
        return results
