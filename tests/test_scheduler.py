from datetime import datetime, timezone

from arqen.mission import MissionScheduler, MissionStore, Schedule


def test_scheduler_creates_due_task_once(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_schedule(Schedule("once", "Brief", "sammanfatta", run_at="2026-09-23T08:00:00+00:00"))
    scheduler = MissionScheduler(store)
    current = datetime(2026, 9, 23, 9, tzinfo=timezone.utc)

    assert len(scheduler.poll(current)) == 1
    assert scheduler.poll(current) == []
    assert store.list_tasks()[0].title == "Brief"


def test_scheduler_matches_simple_cron(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    store.save_schedule(Schedule("hourly", "Hourly", "check", cron="0 9 * * *"))
    assert len(MissionScheduler(store).poll(datetime(2026, 9, 23, 9, tzinfo=timezone.utc))) == 1
