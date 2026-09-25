import json

import pytest

from arqen.ui.theme import VoicePalette, load_voice_palette


def test_voice_palette_applies_valid_overrides_only(tmp_path):
    config = tmp_path / "arqen.json"
    config.write_text(
        json.dumps({"theme": {"voice": {"speaking": "#ff8800", "thinking": "not-a-colour", "unknown": "#ffffff"}}}),
        encoding="utf-8",
    )
    palette = load_voice_palette(config)
    assert palette.speaking == "#ff8800"
    assert palette.thinking == VoicePalette().thinking
    assert not hasattr(palette, "unknown")


def test_voice_palette_falls_back_without_config(tmp_path):
    assert load_voice_palette(tmp_path / "missing.json") == VoicePalette()


def test_voice_panel_states():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from arqen.ui.window import VoiceVisualizationWidget

    app = QApplication.instance() or QApplication([])
    panel = VoiceVisualizationWidget()
    assert panel.state == "idle"
    panel.set_state("thinking")
    assert panel.state == "thinking"
    # Audio from playback overrides the base state until playback reports zero.
    panel._set_audio_level(0.5)
    assert panel.state == "speaking"
    panel._set_audio_level(0.0)
    assert panel.state == "thinking"
    with pytest.raises(ValueError):
        panel.set_state("speaking")
    panel.resize(280, 310)
    assert not panel.grab().isNull()
    panel.deleteLater()
