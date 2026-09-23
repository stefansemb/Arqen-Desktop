from dataclasses import dataclass
from uuid import uuid4

from arqen.mission.contracts import Task
from arqen.mission.runner import MissionRunner
from arqen.mission.store import MissionStore


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    prompt: str
    agent_id: str | None = None


class WorkflowRunner:
    def __init__(self, store: MissionStore, runner: MissionRunner) -> None:
        self.store = store
        self.runner = runner

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
