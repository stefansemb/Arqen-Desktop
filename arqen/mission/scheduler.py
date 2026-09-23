from datetime import datetime, timezone
from uuid import uuid4

from arqen.mission.contracts import Task
from arqen.mission.store import MissionStore


class MissionScheduler:
    def __init__(self, store: MissionStore) -> None:
        self.store = store

    def poll(self, now: datetime | None = None) -> list[Task]:
        current = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
        created: list[Task] = []
        for schedule in self.store.list_schedules():
            if not schedule.enabled or not self._due(schedule, current):
                continue
            task = Task(uuid4().hex, schedule.name, schedule.prompt, agent_id=schedule.agent_id)
            self.store.save_task(task)
            self.store.mark_schedule_run(schedule.id, current.isoformat())
            created.append(task)
        return created

    @staticmethod
    def _due(schedule, current: datetime) -> bool:
        if schedule.last_run_at and schedule.last_run_at[:16] == current.isoformat()[:16]:
            return False
        if schedule.run_at:
            try:
                return datetime.fromisoformat(schedule.run_at).replace(tzinfo=current.tzinfo) <= current
            except ValueError:
                return False
        if not schedule.cron:
            return False
        fields = schedule.cron.split()
        if len(fields) != 5:
            return False
        values = [current.minute, current.hour, current.day, current.month, current.weekday()]
        return all(field == "*" or field.isdigit() and int(field) == value for field, value in zip(fields, values))
