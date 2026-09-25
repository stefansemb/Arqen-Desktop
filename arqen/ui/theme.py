import json
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class CyberpunkGreenTheme:
    background = "#101012"
    panel = "#17181c"
    panel_alt = "#1d1e22"
    border = "#303137"
    accent = "#c7ff2f"
    accent_dim = "#9fce20"
    text = "#f2f0eb"
    muted = "#aaa8a3"
    danger = "#ff6b78"

    @classmethod
    def stylesheet(cls) -> str:
        return f"""
        QWidget {{ background: {cls.background}; color: {cls.text};
                   font-family: Consolas, monospace; font-size: 14px; }}
        QLabel {{ background: transparent; }}
        QFrame#panel {{ background: {cls.panel}; border: 1px solid {cls.border};
                        border-radius: 8px; }}
        QLabel#title {{ color: {cls.accent}; font-size: 22px; font-weight: bold; }}
        QLabel#status {{ color: {cls.muted}; letter-spacing: 1px; }}
        QTextEdit {{ background: {cls.panel_alt}; border: 1px solid {cls.border};
                     border-radius: 6px; padding: 8px; }}
        QLineEdit {{ background: {cls.panel_alt}; border: 1px solid {cls.border};
                     border-radius: 6px; padding: 9px; color: {cls.text}; }}
        QPushButton {{ background: {cls.accent}; color: #101012;
                       border: 0; border-radius: 6px; padding: 9px 16px;
                       font-weight: bold; }}
        QPushButton:hover {{ background: {cls.accent}; }}
        QTabWidget::pane {{ border: 1px solid {cls.border}; background: {cls.panel};
                            border-radius: 6px; }}
        QTabBar::tab {{ background: {cls.panel_alt}; color: {cls.muted};
                        border: 1px solid {cls.border}; padding: 9px 18px;
                        margin-right: 3px; border-top-left-radius: 5px;
                        border-top-right-radius: 5px; }}
        QTabBar::tab:selected {{ background: {cls.accent}; color: #101012;
                                 font-weight: bold; }}
        QTabBar::tab:hover {{ color: {cls.text}; }}
        QPushButton#secondaryButton {{ background: {cls.panel_alt}; color: {cls.accent};
                                       border: 1px solid {cls.accent_dim};
                                       border-radius: 5px; padding: 8px 14px; }}
        QPushButton#secondaryButton:hover {{ background: #292d22; }}
        QPushButton#primaryButton {{ background: {cls.accent}; color: #101012;
                                     border: 1px solid {cls.accent};
                                     border-radius: 5px; padding: 8px 18px;
                                     font-weight: bold; }}
        """


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass(frozen=True)
class VoicePalette:
    """Colours of the ring-based voice panel, one per role rather than per shape.

    Any field can be overridden from ``config/arqen.json`` under
    ``"theme": {"voice": {...}}`` so the panel follows Arqen's theme without
    code changes.
    """

    background: str = "#0b0d0e"
    structure: str = "#2a3431"
    accent: str = CyberpunkGreenTheme.accent
    listening: str = "#4fd8ff"
    thinking: str = CyberpunkGreenTheme.accent
    speaking: str = "#ff9f1c"
    speaking_indicator: str = "#3dff7a"
    text: str = "#e8f5ea"
    muted: str = "#6f7b77"


def load_voice_palette(path: Path | None = None) -> VoicePalette:
    """Default palette merged with valid hex overrides from the config file."""
    palette = VoicePalette()
    if path is None:
        from arqen.config.paths import config_dir

        path = config_dir() / "arqen.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return palette
    theme = data.get("theme") if isinstance(data, dict) else None
    overrides = theme.get("voice") if isinstance(theme, dict) else None
    if not isinstance(overrides, dict):
        return palette
    known = {field.name for field in fields(VoicePalette)}
    valid = {
        key: value
        for key, value in overrides.items()
        if key in known and isinstance(value, str) and _HEX_COLOR.match(value)
    }
    return replace(palette, **valid)
