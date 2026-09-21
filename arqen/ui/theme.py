from dataclasses import dataclass


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
