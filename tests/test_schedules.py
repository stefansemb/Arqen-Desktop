from arqen.mission import MissionStore, Schedule


def test_store_round_trips_and_toggles_schedule(tmp_path):
    store = MissionStore(tmp_path / "mission.sqlite3")
    schedule = Schedule("daily", "Daily brief", "sammanfatta läget", cron="0 8 * * *")
    store.save_schedule(schedule)
    assert store.list_schedules()[0].enabled is True
    store.set_schedule_enabled("daily", False)
    assert store.list_schedules()[0].enabled is False
