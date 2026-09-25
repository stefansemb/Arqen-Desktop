import pytest

from arqen.ui.strings import status_label, tr, tr_status


def test_tr_translates_and_fills_values():
    assert tr("Tasks") == "Uppgifter"
    assert tr("Delete '{title}'?", title="Test") == "Ta bort 'Test'?"


def test_tr_leaves_unknown_text_alone():
    # Model names, file names and user data have no entry and pass through.
    assert tr("xiaomi/mimo-v2.6-pro") == "xiaomi/mimo-v2.6-pro"
    assert tr("Pris {x}") == "Pris {x}"


def test_status_labels_cover_stored_states():
    assert status_label("waiting_approval") == "VÄNTAR PÅ GODKÄNNANDE"
    assert status_label("something_new") == "SOMETHING NEW"


def test_microphone_status_is_translated_part_by_part():
    assert tr_status("MIC // RECORDING") == "MIKROFON // SPELAR IN"
    assert tr_status("MIC // ERROR // device busy") == "MIKROFON // FEL // device busy"


def test_schedule_display_is_swedish():
    pytest.importorskip("PyQt6")
    from arqen.mission import Schedule
    from arqen.ui.window import ArqenWindow

    def show(cron=None, run_at=None):
        return ArqenWindow._schedule_display(Schedule("id", "namn", "gör", cron=cron, run_at=run_at))

    assert show(cron="0 8 * * *") == "Varje dag kl. 08:00"
    assert show(cron="30 7 * * 1") == "Varje måndag kl. 07:30"
    assert show(cron="0 9 1 * *") == "Varje månad den 1 kl. 09:00"
    assert show(run_at=None) == "En gång: inte angivet"
