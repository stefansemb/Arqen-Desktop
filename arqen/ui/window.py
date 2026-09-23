from pathlib import Path

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QInputDialog,
    QMessageBox,
    QDialog,
    QComboBox,
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QDockWidget,
    QSizePolicy,
    QMenu,
    QTabWidget,
    QStackedWidget,
    QFileDialog,
)
from PyQt6.QtCore import QEvent, QObject, QSettings, QThread, QTimer, Qt, QUrl, QPoint, QSize, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QBrush, QPainter, QPalette, QPen, QPixmap
from urllib.request import Request, urlopen
import json
import re
import threading
import time
from pathlib import Path

from arqen.core.engine import ConversationEngine
from arqen.config.settings import (
    load_provider_config,
    save_provider_config,
    load_api_key,
    load_workspace_root,
    save_workspace_root,
)
from arqen.config.paths import APP_ROOT, config_dir, data_dir, workspace_root
from arqen.providers.config import ProviderConfig
from arqen.providers.factory import create_provider
from arqen.ui.theme import CyberpunkGreenTheme
from arqen.core.provider_metrics import ProviderMetrics
from arqen.core.memory_store import MemoryStore
from arqen.tools.speech import set_audio_level_callback
from arqen.tools.microphone import MicrophoneRecorder
from arqen.mission import Agent, MissionRunner, MissionStore, Schedule, Task, Workflow, WorkflowRunner, WorkflowStep
from uuid import uuid4


class ChatBackgroundTextEdit(QTextEdit):
    def __init__(self, background_path: str) -> None:
        super().__init__(readOnly=True)
        self._background = QPixmap(background_path)
        self.setAutoFillBackground(True)
        self.viewport().setAutoFillBackground(True)
        self.viewport().setStyleSheet("background: transparent;")
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#f2f0eb"))
        self.setPalette(palette)
        viewport_palette = self.viewport().palette()
        viewport_palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#f2f0eb"))
        viewport_palette.setColor(QPalette.ColorRole.Text, QColor("#f2f0eb"))
        self.viewport().setPalette(viewport_palette)

    def resizeEvent(self, event) -> None:
        margin = max(24, int(self.width() * 0.08))
        self.setViewportMargins(margin, 0, margin, 0)
        if not self._background.isNull():
            scaled = self._background.scaled(
                self.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            palette = self.viewport().palette()
            palette.setBrush(QPalette.ColorRole.Base, QBrush(scaled))
            self.viewport().setPalette(palette)
        super().resizeEvent(event)


class ResponseWorker(QObject):
    finished = pyqtSignal(str, float)
    failed = pyqtSignal(str)
    tool_requested = pyqtSignal(str)
    confirmation_required = pyqtSignal(str, object)
    cancelled = pyqtSignal()
    partial = pyqtSignal(str)

    def __init__(self, engine: ConversationEngine, prompt: str) -> None:
        super().__init__()
        self.engine = engine
        self.prompt = prompt

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.engine.on_tool_request = lambda name: self.tool_requested.emit(name)
            self.engine.on_partial_response = lambda text: self.partial.emit(text)
            self.engine.on_confirmation_required = (
                lambda name, arguments: self.confirmation_required.emit(name, arguments)
            )
            started = time.perf_counter()
            result = self.engine.respond(self.prompt)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.finished.emit(result, elapsed_ms)
        except Exception as exc:
                self.failed.emit(str(exc))


class MissionWorker(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, runner: MissionRunner, task_id: str) -> None:
        super().__init__()
        self.runner = runner
        self.task_id = task_id

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self.runner.run(self.task_id))
        except Exception as exc:
            self.failed.emit(str(exc))


class ConfirmationWorker(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    tool_requested = pyqtSignal(str)
    confirmation_required = pyqtSignal(str, object)
    partial = pyqtSignal(str)

    def __init__(self, engine: ConversationEngine) -> None:
        super().__init__()
        self.engine = engine

    @pyqtSlot()
    def run(self) -> None:
        try:
            # An approved tool hands the turn back to the model, so the engine
            # callbacks have to point at this worker.  Left pointing at the
            # finished ResponseWorker they would emit from a deleted object.
            self.engine.on_tool_request = lambda name: self.tool_requested.emit(name)
            self.engine.on_partial_response = lambda text: self.partial.emit(text)
            self.engine.on_confirmation_required = (
                lambda name, arguments: self.confirmation_required.emit(name, arguments)
            )
            self.finished.emit(self.engine.confirm_pending_tool(True))
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceVisualizationWidget(QLabel):
    """Static visual shell; audio-driven animation will be added without changing the dock."""

    audio_level_changed = pyqtSignal(float)

    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap(str(image_path))
        self._pulse_angle = 0.0
        self._audio_level = 0.0
        self._wave_phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self._pulse_timer.start()
        self.audio_level_changed.connect(self._set_audio_level)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #0b0d0e; border: 1px solid #303538; border-radius: 6px;")
        self._refresh_pixmap()

    def resizeEvent(self, event) -> None:
        self._refresh_pixmap()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center() + QPoint(-5, -5)
        base_radius = min(self.width(), self.height()) * 0.245
        import math

        idle_pulse = (math.sin(self._pulse_angle) + 1.0) / 2.0 * 0.08
        pulse = max(idle_pulse, self._audio_level)
        radius = base_radius + pulse * 7.0
        alpha = int(45 + pulse * 40)
        pen = QPen(QColor(183, 255, 24, alpha), 3.0)
        painter.setPen(pen)
        painter.drawEllipse(center, int(radius), int(radius))
        self._paint_dynamic_waveform(painter, center)
        painter.end()

    def _advance_pulse(self) -> None:
        self._pulse_angle = (self._pulse_angle + 0.12) % (2 * 3.141592653589793)
        self._wave_phase = (self._wave_phase + 0.16) % (2 * 3.141592653589793)
        self.update()

    def set_audio_level(self, level: float) -> None:
        self.audio_level_changed.emit(level)

    def _set_audio_level(self, level: float) -> None:
        self._audio_level = level
        self.update()

    def _paint_dynamic_waveform(self, painter: QPainter, center: QPoint) -> None:
        """Draw a compact responsive waveform over the baked-in image waveform."""
        import math

        width = min(self.width() * 0.52, 235.0)
        height = min(self.height() * 0.18, 58.0)
        # Cover only the old baked waveform, leaving the surrounding inner ring visible.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(7, 11, 10, 225))
        mask_radius = min(self.width(), self.height()) * 0.255
        painter.drawEllipse(center, int(mask_radius), int(mask_radius))
        level = max(0.045, self._audio_level)
        points = []
        samples = 96
        for index in range(samples):
            position = index / (samples - 1)
            envelope = math.sin(math.pi * position) ** 0.7
            texture = (
                0.48 * math.sin(position * 29.0 + self._wave_phase)
                + 0.28 * math.sin(position * 61.0 - self._wave_phase * 1.7)
                + 0.14 * math.sin(position * 113.0 + self._wave_phase * 0.6)
            )
            y = center.y() + texture * envelope * level * height
            x = center.x() - width / 2 + position * width
            points.append((int(x), int(y)))
        pen = QPen(QColor(195, 255, 45, int(180 + level * 75)), 2.0)
        painter.setPen(pen)
        for first, second in zip(points, points[1:]):
            painter.drawLine(first[0], first[1], second[0], second[1])
        painter.setPen(QPen(QColor(220, 255, 105, 210), 1.0))
        mirror = [(x, int(2 * center.y() - y)) for x, y in points]
        for first, second in zip(mirror, mirror[1:]):
            painter.drawLine(first[0], first[1], second[0], second[1])

    def sizeHint(self) -> QSize:
        return QSize(400, 300)

    def minimumSizeHint(self) -> QSize:
        return QSize(300, 220)

    def _refresh_pixmap(self) -> None:
        if not self._pixmap.isNull():
            self.setPixmap(self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))



_EMPHASIS = re.compile(r"\*\*(?P<strong>[^*\n]+?)\*\*|\*(?P<em>[^*\s][^*\n]*?)\*")


def strip_emphasis(text: str) -> str:
    """Drop markdown emphasis markers without touching arithmetic.

    Streamed text is inserted as plain text, so ``**like this**`` would show
    its asterisks.  Removing every asterisk instead turned ``c * r`` into
    ``c r`` and quietly corrupted any code the model wrote, so only matched
    pairs that sit flush against their content are removed.
    """
    return _EMPHASIS.sub(lambda match: match.group("strong") or match.group("em"), text.replace("\\*", "*"))


# Long enough for any reasonable run of bold text, short enough that a stray
# asterisk cannot stall the stream for the rest of the answer.
_PENDING_LIMIT = 240


def split_pending(text: str) -> tuple[str, str]:
    """Split streamed text into what can be shown and what must wait.

    Emphasis arrives in pieces -- ``**vik`` in one chunk and ``tigt**`` in the
    next -- so an asterisk that still has no partner is held back until the
    rest catches up.  An asterisk with space on both sides is arithmetic and
    never a marker, so it goes straight through.
    """
    text = strip_emphasis(text)
    last = text.rfind("*")
    if last < 0 or len(text) > _PENDING_LIMIT:
        return text, ""
    # ``**`` is one marker: splitting inside the run would leak half of it.
    start = last
    while start > 0 and text[start - 1] == "*":
        start -= 1
    if last + 1 == len(text):
        # Nothing has arrived after it yet, so there is nothing to judge by.
        return text[:start], text[start:]
    after = text[last + 1]
    return (text[:start], text[start:]) if not after.isspace() else (text, "")


class StatsPanelWidget(QWidget):
    """Tokens and cost for the session, and for everything recorded so far."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        self._rows: dict[str, QLabel] = {}
        self._heading(layout, "DEN HÄR SESSIONEN")
        for key, label in (("session_tokens", "Tokens"), ("session_split", "In / out"), ("session_cost", "Cost")):
            self._row(layout, key, label)
        layout.addSpacing(8)
        self._heading(layout, "TOTALT")
        for key, label in (("total_tokens", "Tokens"), ("total_cost", "Cost")):
            self._row(layout, key, label)
        layout.addSpacing(8)
        self._heading(layout, "LATEST RESPONSE")
        for key, label in (("last_turn", "Tokens"), ("last_cost", "Cost"), ("last_ms", "Time")):
            self._row(layout, key, label)
        layout.addStretch(1)
        self.setStyleSheet(
            f"background-color: {CyberpunkGreenTheme.panel}; "
            f"color: {CyberpunkGreenTheme.text};"
        )
        self.update_usage(None, None, None, None)

    def _heading(self, layout: QVBoxLayout, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {CyberpunkGreenTheme.accent}; letter-spacing: 2px; font-size: 10px;"
        )
        layout.addWidget(label)

    def _row(self, layout: QVBoxLayout, key: str, caption: str) -> None:
        line = QHBoxLayout()
        name = QLabel(caption)
        name.setStyleSheet(f"color: {CyberpunkGreenTheme.muted}; font-size: 11px;")
        value = QLabel("—")
        value.setStyleSheet(
            f"color: {CyberpunkGreenTheme.text}; font-family: Consolas, monospace; font-size: 12px;"
        )
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(name)
        line.addStretch(1)
        line.addWidget(value)
        layout.addLayout(line)
        self._rows[key] = value

    @staticmethod
    def _money(amount: float) -> str:
        """Small amounts need more decimals than a price tag does."""
        if amount <= 0:
            return "$0.00"
        if amount < 0.01:
            return f"${amount:.5f}"
        return f"${amount:.2f}"

    @staticmethod
    def _count(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    def update_usage(self, session, total, turn, elapsed_ms) -> None:
        if session is None:
            for value in self._rows.values():
                value.setText("—")
            return
        self._rows["session_tokens"].setText(self._count(session.total_tokens))
        self._rows["session_split"].setText(
            f"{self._count(session.prompt_tokens)} / {self._count(session.completion_tokens)}"
        )
        self._rows["session_cost"].setText(self._money(session.cost))
        self._rows["total_tokens"].setText(self._count(total.total_tokens))
        self._rows["total_cost"].setText(self._money(total.cost))
        if turn is not None:
            self._rows["last_turn"].setText(self._count(turn.total_tokens))
            self._rows["last_cost"].setText(self._money(turn.cost))
        self._rows["last_ms"].setText("—" if elapsed_ms is None else f"{elapsed_ms / 1000:.1f} s")


class ArqenWindow(QMainWindow):
    microphone_status = pyqtSignal(str)
    microphone_result = pyqtSignal(str)

    def __init__(self, engine: ConversationEngine, provider_label: str = "unknown", profile_name: str = "") -> None:
        super().__init__()
        self.engine = engine
        self.engine.on_tool_request = self.show_tool_request
        self.setWindowTitle("Arqen Desktop")
        self.resize(900, 620)
        self.setStyleSheet(CyberpunkGreenTheme.stylesheet())

        root = QWidget()
        layout = QHBoxLayout(root)
        navigation = QFrame(objectName="panel")
        navigation.setFixedWidth(198)
        navigation.setStyleSheet(
            "QFrame#panel { background: #0e1115; border-right: 1px solid #20262b; }"
            "QLabel#navSection { color: #657078; font-size: 9px; letter-spacing: 1px; padding-top: 14px; }"
            "QPushButton#navButton { background: transparent; color: #8d969d; border: none; text-align: left; padding: 7px 8px; border-radius: 5px; }"
            "QPushButton#navButton:hover { background: #171d21; color: #dbe2df; }"
        )
        navigation_layout = QVBoxLayout(navigation)
        self.navigation_buttons: dict[str, QPushButton] = {}
        navigation_layout.addWidget(QLabel("ARQEN", objectName="title"))
        navigation_layout.addWidget(QLabel("MISSION CONTROL"))
        navigation_layout.addWidget(QLabel("OVERVIEW", objectName="navSection"))
        for label, icon in (("Dashboard", "⌂"), ("Chat", "◌"), ("Mission Control", "◈")):
            self._add_navigation_button(navigation_layout, label, icon)
        navigation_layout.addWidget(QLabel("SYSTEM", objectName="navSection"))
        for label, icon in (("Agents", "♙"), ("Activity", "≋"), ("Memory", "▤")):
            self._add_navigation_button(navigation_layout, label, icon)
        navigation_layout.addWidget(QLabel("OPERATIONS", objectName="navSection"))
        for label, icon in (("Tasks", "✓"), ("Workflows", "⌘"), ("Schedules", "◷"), ("Content", "◇")):
            self._add_navigation_button(navigation_layout, label, icon)
        navigation_layout.addStretch(1)
        settings_nav = QPushButton("⚙  Settings")
        settings_nav.setObjectName("navButton")
        settings_nav.clicked.connect(self.open_settings)
        navigation_layout.addWidget(settings_nav)
        layout.addWidget(navigation)
        sidebar = QFrame(objectName="panel")
        sidebar.setFixedWidth(320)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("CHATS", objectName="title"))
        new_chat = QPushButton("NEW CHAT")
        new_chat.clicked.connect(self.create_new_session)
        sidebar_layout.addWidget(new_chat)
        self.session_list = QListWidget()
        self.session_list.setWordWrap(True)
        self.session_list.setUniformItemSizes(False)
        self.session_list.itemClicked.connect(lambda _: self.load_selected_session())
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.show_session_menu)
        sidebar_layout.addWidget(self.session_list, 1)
        icon_row = QHBoxLayout()
        self.mic_button = QPushButton("🎙")
        self.mic_button.setToolTip("Start/stop microphone recording")
        self.mic_button.setAccessibleName("Start/stop microphone recording")
        self.mic_button.clicked.connect(self.toggle_microphone)
        self.voice_button = QPushButton("🔇")
        self.voice_button.setToolTip("Toggle voice mode")
        self.voice_button.setAccessibleName("Toggle voice mode")
        self.voice_button.clicked.connect(self.toggle_voice_mode)
        settings_button = QPushButton("⚙")
        settings_button.setToolTip("Inställningar")
        settings_button.setAccessibleName("Inställningar")
        settings_button.clicked.connect(self.open_settings)
        for button in (self.mic_button, self.voice_button, settings_button):
            button.setMinimumWidth(0)
            button.setStyleSheet(
                "QPushButton { background: transparent; color: #b7ff18; border: none; "
                "font-size: 20px; padding: 2px 8px; }"
                "QPushButton:hover { color: #e1ff8a; background: #252a20; }"
            )
            icon_row.addWidget(button)
        sidebar_layout.addLayout(icon_row)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        session_bar = QHBoxLayout()
        session_bar.addWidget(QLabel("SESSION"))
        self.chat_session_selector = QComboBox()
        self.chat_session_selector.setMinimumWidth(220)
        self.chat_session_selector.activated.connect(self._load_selected_chat_from_bar)
        session_bar.addWidget(self.chat_session_selector, 1)
        new_chat_button = QPushButton("NEW CHAT")
        self._style_page_action(new_chat_button, primary=True)
        new_chat_button.clicked.connect(self.create_new_session)
        session_bar.addWidget(new_chat_button)
        content_layout.addLayout(session_bar)
        header = QFrame(objectName="panel")
        header_layout = QVBoxLayout(header)
        header_layout.addWidget(QLabel("ARQEN DESKTOP", objectName="title"))
        self.provider_label = provider_label
        self.profile_name = profile_name
        self.status = QLabel(
            self.provider_status("READY"),
            objectName="status",
        )
        header_layout.addWidget(self.status)

        self.output = QTextEdit(readOnly=True)
        self.output.setPlaceholderText("")
        self.output.setStyleSheet(
            "QTextEdit { background: transparent; color: #f2f0eb; "
            "border: 1px solid #303137; border-radius: 6px; padding: 8px; }"
        )
        chat_surface = QWidget()
        chat_surface.setObjectName("chatSurface")
        chat_surface.setStyleSheet("QWidget#chatSurface { background: #17181c; border-radius: 6px; }")
        chat_surface_layout = QGridLayout(chat_surface)
        chat_surface_layout.setContentsMargins(0, 0, 0, 0)
        chat_surface_layout.addWidget(self.output, 0, 0)
        placeholder_label = QLabel("Conversation will appear here...", chat_surface)
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        placeholder_label.setStyleSheet("color: #f2f0eb; background: transparent; padding-top: 8px;")
        placeholder_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        chat_surface_layout.addWidget(placeholder_label, 0, 0)
        self.output.textChanged.connect(lambda: placeholder_label.setVisible(not bool(self.output.toPlainText())))
        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message...")
        self.microphone_status.connect(self.set_status)
        self.microphone_result.connect(self._handle_microphone_result)
        self.microphone = MicrophoneRecorder(
            on_result=self.microphone_result.emit,
            on_status=self.microphone_status.emit,
        )
        self.input.returnPressed.connect(self.send_message)
        send = QPushButton("▶")
        send.setToolTip("Send")
        send.setAccessibleName("Send")
        send.setStyleSheet("QPushButton { background: transparent; color: #b7ff18; border: none; font-size: 32px; font-weight: 700; padding: 5px 8px 0 8px; } QPushButton:hover { color: #e1ff8a; }")
        send.clicked.connect(self.send_message)
        self.stop_button = QPushButton("■")
        self.stop_button.setToolTip("Stop")
        self.stop_button.setAccessibleName("Stop")
        self.stop_button.setStyleSheet("QPushButton { background: transparent; color: #b7ff18; border: none; font-size: 28px; font-weight: 700; padding: 0 8px; } QPushButton:hover { color: #e1ff8a; }")
        self.stop_button.clicked.connect(self.stop_response)
        self.stop_button.setEnabled(False)
        self.confirm_button = QPushButton("CONFIRM")
        self.cancel_button = QPushButton("CANCEL")
        self.confirm_button.clicked.connect(lambda: self.resolve_confirmation(True))
        self.cancel_button.clicked.connect(lambda: self.resolve_confirmation(False))
        self.confirm_button.setVisible(False)
        self.cancel_button.setVisible(False)
        input_row.addWidget(self.input)
        input_row.addWidget(send)
        input_row.addWidget(self.stop_button)
        input_row.addWidget(self.confirm_button)
        input_row.addWidget(self.cancel_button)

        content_layout.addWidget(header)
        content_layout.addWidget(chat_surface, 1)
        content_layout.addLayout(input_row)
        sidebar.hide()
        self.navigation_stack = QStackedWidget()
        dashboard = QWidget()
        dashboard_layout = QVBoxLayout(dashboard)
        dashboard_layout.addWidget(QLabel("DASHBOARD", objectName="title"))
        dashboard_layout.addWidget(QLabel("Mission Control // system overview"))
        cards = QGridLayout()
        self.dashboard_cards: dict[str, QLabel] = {}
        for index, (key, label) in enumerate((("agents", "AGENTS"), ("tasks", "ACTIVE TASKS"), ("approvals", "APPROVALS"), ("workflows", "WORKFLOW RUNS"))):
            card = QFrame(objectName="panel")
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(QLabel(label))
            value = QLabel("0", objectName="title")
            card_layout.addWidget(value)
            self.dashboard_cards[key] = value
            cards.addWidget(card, index // 2, index % 2)
        dashboard_layout.addLayout(cards)
        dashboard_layout.addWidget(QLabel("LATEST ACTIVITY", objectName="title"))
        self.dashboard_activity = QListWidget()
        dashboard_layout.addWidget(self.dashboard_activity, 1)
        open_chat = QPushButton("OPEN ARQEN CHAT")
        self._style_page_action(open_chat, primary=True)
        open_chat.clicked.connect(lambda: self.navigation_stack.setCurrentIndex(1))
        dashboard_layout.addWidget(open_chat)
        self.navigation_stack.addWidget(dashboard)
        self.navigation_stack.addWidget(content)
        for label in ("Tasks", "Workflows", "Schedules", "Agents", "Activity", "Memory", "Content"):
            if label == "Tasks":
                self._add_tasks_view()
                continue
            if label == "Workflows":
                self._add_workflows_view()
                continue
            if label == "Schedules":
                self._add_schedules_view()
                continue
            if label == "Agents":
                self._add_agents_view()
                continue
            if label == "Activity":
                self._add_activity_view()
                continue
            if label == "Memory":
                self._add_memory_view()
                continue
            if label == "Content":
                self._add_content_view()
                continue
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(QLabel(label.upper(), objectName="title"))
            page_layout.addWidget(QLabel("This view will be expanded in the next UI step."))
            page_layout.addStretch(1)
            self.navigation_stack.addWidget(page)
        layout.addWidget(self.navigation_stack, 1)
        self.setCentralWidget(root)
        self._create_visualization_dock()
        self.engine.on_confirmation_required = self.show_confirmation
        self._streaming_displayed = False
        self._cancel_requested = False
        self._stream_candidate = ""
        self.last_response_ms: float | None = None
        self.fallback_count = 0
        self.provider_metrics = ProviderMetrics()
        self._create_stats_dock()
        self._create_mission_dock()
        self._restore_window_geometry()
        self._loading_phase = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(350)
        self._loading_timer.timeout.connect(self._animate_loading)
        self.refresh_sessions()
        self._select_navigation("Dashboard")

    def _add_tasks_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("TASKS", objectName="title"))
        page_layout.addWidget(QLabel("Monitor, run and retry agent work."))
        self.mission_tasks = QListWidget()
        self.mission_tasks.itemClicked.connect(self._show_mission_task)
        page_layout.addWidget(self.mission_tasks, 1)
        self.mission_details = QTextEdit(readOnly=True)
        self.mission_details.setPlaceholderText("Select a task to view status and events.")
        page_layout.addWidget(self.mission_details)
        page_layout.addWidget(QLabel("PENDING APPROVALS", objectName="sectionLabel"))
        self.mission_approvals = QListWidget()
        self.mission_approvals.itemClicked.connect(self._show_selected_approval)
        page_layout.addWidget(self.mission_approvals)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW TASK", self._create_mission_task), ("RUN SELECTED TASK", self._run_mission_task), ("RETRY", self._retry_mission_task))):
            button = QPushButton(label)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        page_layout.addLayout(row)
        approval_row = QHBoxLayout()
        for index, (label, status) in enumerate((("APPROVE", "approved"), ("REJECT", "rejected"))):
            button = QPushButton(label)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(lambda _, value=status: self._decide_mission_approval(value))
            approval_row.addWidget(button)
        page_layout.addLayout(approval_row)
        self.navigation_stack.addWidget(page)

    def _add_workflows_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("WORKFLOWS", objectName="title"))
        page_layout.addWidget(QLabel("Build and run multi-agent pipelines."))
        self.mission_workflows = QListWidget()
        page_layout.addWidget(self.mission_workflows)
        self.mission_workflow_runs = QListWidget()
        page_layout.addWidget(self.mission_workflow_runs)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW WORKFLOW", self._create_mission_workflow), ("RUN WORKFLOW", self._run_mission_workflow), ("RESUME RUN", self._resume_mission_workflow))):
            button = QPushButton(label)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        page_layout.addLayout(row)
        self.navigation_stack.addWidget(page)

    def _add_schedules_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("SCHEDULES", objectName="title"))
        page_layout.addWidget(QLabel("Automate recurring tasks and workflows."))
        self.mission_schedules = QListWidget()
        page_layout.addWidget(self.mission_schedules, 1)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW SCHEDULE", self._create_mission_schedule), ("ENABLE/DISABLE", self._toggle_mission_schedule))):
            button = QPushButton(label)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        page_layout.addLayout(row)
        self.navigation_stack.addWidget(page)

    def _add_agents_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("AGENTS", objectName="title"))
        page_layout.addWidget(QLabel("Manage runtimes, tools and approval policies."))
        self.mission_agents = QListWidget()
        page_layout.addWidget(self.mission_agents, 1)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW AGENT", self._create_mission_agent), ("EDIT", self._edit_mission_agent), ("ENABLE/DISABLE", self._toggle_mission_agent))):
            button = QPushButton(label)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        page_layout.addLayout(row)
        self.navigation_stack.addWidget(page)

    def _style_page_action(self, button: QPushButton, *, primary: bool = False) -> None:
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            button.setStyleSheet(
                "QPushButton { background: #111516; color: #d8ff75; border: 1px solid #b7ff18; border-radius: 5px; padding: 9px 14px; font-weight: 700; }"
                "QPushButton:hover { background: #1b2418; color: #e7ffad; } QPushButton:pressed { background: #27351e; }"
            )
        else:
            button.setStyleSheet(
                "QPushButton { background: #171d21; color: #c4cec9; border: 1px solid #30383a; border-radius: 5px; padding: 9px 14px; }"
                "QPushButton:hover { background: #20282a; color: #f2f0eb; border-color: #66736e; } QPushButton:pressed { background: #111516; }"
            )

    def _add_activity_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("ACTIVITY", objectName="title"))
        page_layout.addWidget(QLabel("Live system events and agent activity."))
        self.activity_view_list = QListWidget()
        self.activity_view_list.itemClicked.connect(self._open_activity_task)
        page_layout.addWidget(self.activity_view_list, 1)
        self.activity_view_timer = QTimer(self)
        self.activity_view_timer.setInterval(2000)
        self.activity_view_timer.timeout.connect(self._refresh_activity_view)
        self.activity_view_timer.start()
        self.navigation_stack.addWidget(page)

    def _refresh_activity_view(self) -> None:
        if not hasattr(self, "activity_view_list") or not hasattr(self, "mission_store"):
            return
        self.refresh_mission_activity()

    def _add_memory_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("MEMORY", objectName="title"))
        page_layout.addWidget(QLabel("User-approved long-term context."))
        self.memory_view_list = QListWidget()
        page_layout.addWidget(self.memory_view_list, 1)
        refresh = QPushButton("REFRESH MEMORY")
        self._style_page_action(refresh)
        refresh.clicked.connect(self._refresh_memory_view)
        page_layout.addWidget(refresh)
        self._refresh_memory_view()
        self.navigation_stack.addWidget(page)

    def _refresh_memory_view(self) -> None:
        if not hasattr(self, "memory_view_list"):
            return
        self.memory_view_list.clear()
        for item in MemoryStore().list():
            self.memory_view_list.addItem(str(item))

    def _add_content_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel("CONTENT", objectName="title"))
        page_layout.addWidget(QLabel("Generated files and workflow artifacts."))
        self.content_view_list = QListWidget()
        page_layout.addWidget(self.content_view_list, 1)
        refresh = QPushButton("REFRESH CONTENT")
        self._style_page_action(refresh)
        refresh.clicked.connect(self._refresh_content_view)
        page_layout.addWidget(refresh)
        self._refresh_content_view()
        self.navigation_stack.addWidget(page)

    def _refresh_content_view(self) -> None:
        if not hasattr(self, "content_view_list"):
            return
        self.content_view_list.clear()
        root = data_dir()
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.name != "mission.sqlite3":
                    self.content_view_list.addItem(str(path.relative_to(root)))

    def _add_navigation_button(self, layout: QVBoxLayout, label: str, icon: str) -> None:
        button = QPushButton(f"{icon}  {label}")
        button.setObjectName("navButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _, name=label: self._select_navigation(name))
        layout.addWidget(button)
        self.navigation_buttons[label] = button

    def _select_navigation(self, name: str) -> None:
        self.status.setText(self.provider_status(f"{name.upper()}"))
        for label, button in getattr(self, "navigation_buttons", {}).items():
            button.setProperty("active", label == name)
            button.setStyleSheet(
                "QPushButton { background: #171d21; color: #dbe2df; border: none; "
                "border-left: 2px solid #b7ff18; text-align: left; padding: 7px 8px; border-radius: 5px; }"
                if label == name else
                "QPushButton { background: transparent; color: #8d969d; border: none; "
                "text-align: left; padding: 7px 8px; border-radius: 5px; }"
            )
        pages = {"Dashboard": 0, "Chat": 1, "Tasks": 2, "Workflows": 3, "Schedules": 4, "Agents": 5, "Activity": 6, "Memory": 7, "Content": 8, "Mission Control": getattr(self, "mission_page_index", 0)}
        if name in pages and hasattr(self, "navigation_stack"):
            self.navigation_stack.setCurrentIndex(pages[name])
            if name == "Memory":
                self._refresh_memory_view()
            elif name == "Content":
                self._refresh_content_view()

    def _create_mission_dock(self) -> None:
        """Create the first functional Mission Control surface."""
        self.mission_store = MissionStore(data_dir() / "mission.sqlite3")
        self.mission_runner = MissionRunner(self.mission_store, lambda: self.engine)
        self.workflow_runner = WorkflowRunner(self.mission_store, self.mission_runner)
        dock = QDockWidget("MISSION CONTROL", self)
        dock.setObjectName("missionControlDock")
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(QLabel("WORKFLOWS"))
        legacy_workflows = QListWidget()
        panel_layout.addWidget(legacy_workflows)
        legacy_workflow_runs = QListWidget()
        panel_layout.addWidget(legacy_workflow_runs)
        workflow_row = QHBoxLayout()
        new_workflow = QPushButton("NEW WORKFLOW")
        run_workflow = QPushButton("RUN WORKFLOW")
        resume_workflow = QPushButton("RESUME RUN")
        new_workflow.clicked.connect(self._create_mission_workflow)
        run_workflow.clicked.connect(self._run_mission_workflow)
        resume_workflow.clicked.connect(self._resume_mission_workflow)
        workflow_row.addWidget(new_workflow)
        workflow_row.addWidget(run_workflow)
        workflow_row.addWidget(resume_workflow)
        panel_layout.addLayout(workflow_row)
        panel_layout.addWidget(QLabel("ACTIVITY"))
        self.mission_activity = QListWidget()
        self.mission_activity.itemClicked.connect(self._open_activity_task)
        panel_layout.addWidget(self.mission_activity)
        self.mission_activity_timer = QTimer(self)
        self.mission_activity_timer.setInterval(2000)
        self.mission_activity_timer.timeout.connect(self.refresh_mission_activity)
        self.mission_activity_timer.timeout.connect(self.refresh_dashboard)
        self.mission_activity_timer.start()
        panel_layout.addWidget(QLabel("SCHEDULES"))
        legacy_schedules = QListWidget()
        panel_layout.addWidget(legacy_schedules)
        schedule_row = QHBoxLayout()
        new_schedule = QPushButton("NEW SCHEDULE")
        toggle_schedule = QPushButton("ENABLE/DISABLE")
        new_schedule.clicked.connect(self._create_mission_schedule)
        toggle_schedule.clicked.connect(self._toggle_mission_schedule)
        schedule_row.addWidget(new_schedule)
        schedule_row.addWidget(toggle_schedule)
        panel_layout.addLayout(schedule_row)
        panel_layout.addWidget(QLabel("AGENTS"))
        legacy_agents = QListWidget()
        panel_layout.addWidget(legacy_agents)
        agent_row = QHBoxLayout()
        new_agent = QPushButton("NEW AGENT")
        edit_agent = QPushButton("EDIT")
        toggle_agent = QPushButton("ENABLE/DISABLE")
        new_agent.clicked.connect(self._create_mission_agent)
        edit_agent.clicked.connect(self._edit_mission_agent)
        toggle_agent.clicked.connect(self._toggle_mission_agent)
        agent_row.addWidget(new_agent)
        agent_row.addWidget(edit_agent)
        agent_row.addWidget(toggle_agent)
        panel_layout.addLayout(agent_row)
        legacy_tasks = QListWidget()
        legacy_tasks.itemClicked.connect(self._show_mission_task)
        panel_layout.addWidget(legacy_tasks, 1)
        panel_layout.addWidget(QLabel("PENDING APPROVALS"))
        legacy_approvals = QListWidget()
        legacy_approvals.itemClicked.connect(self._show_selected_approval)
        panel_layout.addWidget(legacy_approvals)
        approval_row = QHBoxLayout()
        approve = QPushButton("APPROVE")
        reject = QPushButton("REJECT")
        approve.clicked.connect(lambda: self._decide_mission_approval("approved"))
        reject.clicked.connect(lambda: self._decide_mission_approval("rejected"))
        approval_row.addWidget(approve)
        approval_row.addWidget(reject)
        panel_layout.addLayout(approval_row)
        create = QPushButton("NEW TASK")
        create.clicked.connect(self._create_mission_task)
        run = QPushButton("RUN SELECTED TASK")
        run.clicked.connect(self._run_mission_task)
        retry = QPushButton("RETRY")
        retry.clicked.connect(self._retry_mission_task)
        legacy_details = QTextEdit(readOnly=True)
        legacy_details.setPlaceholderText("Select a task to view status and events.")
        panel_layout.addWidget(legacy_details)
        panel_layout.addWidget(create)
        panel_layout.addWidget(run)
        panel_layout.addWidget(retry)
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.mission_dock = dock
        mission_page = dock.widget()
        dock.setWidget(None)
        self.mission_page_index = self.navigation_stack.addWidget(mission_page)
        dock.hide()
        self.refresh_mission_tasks()
        self.refresh_mission_approvals()
        self.refresh_mission_agents()
        self.refresh_mission_schedules()
        self.refresh_mission_workflows()
        self.refresh_mission_activity()
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        if not hasattr(self, "dashboard_cards"):
            return
        self.dashboard_cards["agents"].setText(str(len(self.mission_store.list_agents())))
        active = sum(1 for task in self.mission_store.list_tasks() if task.status in {"queued", "running", "waiting_approval"})
        self.dashboard_cards["tasks"].setText(str(active))
        self.dashboard_cards["approvals"].setText(str(len(self.mission_store.list_approvals("pending"))))
        self.dashboard_cards["workflows"].setText(str(len(self.mission_store.list_workflow_runs())))
        self.dashboard_activity.clear()
        for event in self.mission_store.list_all_events(8):
            self.dashboard_activity.addItem(f"[{event.kind}] {event.message}")

    def refresh_mission_activity(self) -> None:
        target = getattr(self, "activity_view_list", self.mission_activity)
        target.clear()
        for event in self.mission_store.list_all_events(50):
            item = QListWidgetItem(f"{event.created_at} [{event.kind}] {event.message}")
            item.setData(Qt.ItemDataRole.UserRole, event.task_id)
            if event.kind in {"failed", "approval_rejected"}:
                item.setForeground(QColor("#ff6b6b"))
            elif event.kind in {"waiting_approval", "approval_requested"}:
                item.setForeground(QColor("#ffd166"))
            elif event.kind == "completed":
                item.setForeground(QColor("#b7ff18"))
            target.addItem(item)

    def _open_activity_task(self, item: QListWidgetItem) -> None:
        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = self.mission_store.get_task(task_id)
        if task is None:
            return
        for index in range(self.mission_tasks.count()):
            candidate = self.mission_tasks.item(index)
            if candidate.data(Qt.ItemDataRole.UserRole) == task.id:
                self.mission_tasks.setCurrentItem(candidate)
                self._show_mission_task()
                return
        self.refresh_mission_workflow_runs()

    def _show_selected_approval(self, item: QListWidgetItem) -> None:
        approval = self.mission_store.get_approval(item.data(Qt.ItemDataRole.UserRole))
        if approval:
            self.mission_details.setPlainText(
                f"Approval\nAction: {approval.action}\nTask: {approval.task_id}\nStatus: {approval.status}\n\n"
                f"{json.dumps(approval.payload, ensure_ascii=False, indent=2)}"
            )

    def refresh_mission_workflows(self) -> None:
        self.mission_workflows.clear()
        for workflow in self.mission_store.list_workflows():
            item = QListWidgetItem(f"[{len(workflow.steps)} steps] {workflow.name}")
            item.setData(Qt.ItemDataRole.UserRole, workflow.id)
            item.setToolTip("\n".join(f"{step.name} → {step.agent_id or 'Arqen'}" for step in workflow.steps))
            self.mission_workflows.addItem(item)

    def refresh_mission_workflow_runs(self) -> None:
        self.mission_workflow_runs.clear()
        for run in self.mission_store.list_workflow_runs():
            item = QListWidgetItem(f"[{run.status.upper()}] {run.workflow_id} // step {run.current_step} // {run.id[:8]}")
            item.setData(Qt.ItemDataRole.UserRole, run.id)
            item.setToolTip("\n".join(run.results) or "Inga resultat ännu")
            self.mission_workflow_runs.addItem(item)

    def _create_mission_workflow(self) -> None:
        name, accepted = QInputDialog.getText(self, "New workflow", "Name:")
        if not accepted or not name.strip():
            return
        raw, accepted = QInputDialog.getMultiLineText(self, "New workflow", "One step per line: name | prompt | agent-id (optional)")
        if not accepted:
            return
        steps = []
        for line in raw.splitlines():
            parts = [part.strip() for part in line.split("|", 2)]
            if len(parts) >= 2 and parts[0] and parts[1]:
                steps.append(WorkflowStep(parts[0], parts[1], parts[2] if len(parts) == 3 and parts[2] else None))
        if not steps:
            QMessageBox.warning(self, "Mission Control", "At least one valid step is required.")
            return
        self.mission_store.save_workflow(Workflow(uuid4().hex, name.strip(), tuple(steps)))
        self.refresh_mission_workflows()

    def _run_mission_workflow(self) -> None:
        item = self.mission_workflows.currentItem()
        if item is None:
            return
        workflow = next((entry for entry in self.mission_store.list_workflows() if entry.id == item.data(Qt.ItemDataRole.UserRole)), None)
        if workflow is None:
            return
        try:
            self.workflow_runner.run(workflow.name, list(workflow.steps))
        except Exception as exc:
            QMessageBox.warning(self, "Mission Control", str(exc))
        self.refresh_mission_tasks()
        self.refresh_mission_workflow_runs()

    def _resume_mission_workflow(self) -> None:
        item = self.mission_workflow_runs.currentItem()
        if item is None:
            return
        run = self.mission_store.get_workflow_run(item.data(Qt.ItemDataRole.UserRole))
        if run is None or run.status != "waiting_approval":
            return
        try:
            self.workflow_runner.resume(run.id)
        except Exception as exc:
            QMessageBox.warning(self, "Mission Control", str(exc))
        self.refresh_mission_tasks()
        self.refresh_mission_workflow_runs()

    def refresh_mission_schedules(self) -> None:
        self.mission_schedules.clear()
        for schedule in self.mission_store.list_schedules():
            mode = schedule.cron or f"once: {schedule.run_at}"
            state = "ON" if schedule.enabled else "OFF"
            agent = self.mission_store.get_agent(schedule.agent_id) if schedule.agent_id else None
            workflow = next((item for item in self.mission_store.list_workflows() if item.id == schedule.workflow_id), None) if schedule.workflow_id else None
            count = sum(1 for task in self.mission_store.list_tasks() if task.schedule_id == schedule.id)
            last = schedule.last_run_at or "aldrig"
            target = f"workflow: {workflow.name}" if workflow else f"task: {agent.name if agent else 'Arqen'}"
            item = QListWidgetItem(f"[{state}] {schedule.name} // {mode} // {target} // tasks: {count}")
            item.setData(Qt.ItemDataRole.UserRole, schedule.id)
            item.setToolTip(f"Senaste körning: {last}")
            self.mission_schedules.addItem(item)

    def _create_mission_schedule(self) -> None:
        name, accepted = QInputDialog.getText(self, "New schedule", "Name:")
        if not accepted or not name.strip():
            return
        prompt, accepted = QInputDialog.getMultiLineText(self, "New schedule", "Task instruction:")
        if not accepted or not prompt.strip():
            return
        mode, accepted = QInputDialog.getItem(self, "New schedule", "Type:", ["Cron", "One-time"], 0, False)
        if not accepted:
            return
        if mode == "Cron":
            cron, accepted = QInputDialog.getText(self, "New schedule", "Cron (e.g. 0 8 * * *):")
            if not accepted or not cron.strip():
                return
            schedule = Schedule(uuid4().hex, name.strip(), prompt.strip(), cron=cron.strip())
        else:
            run_at, accepted = QInputDialog.getText(self, "New schedule", "Time (ISO-8601 UTC):")
            if not accepted or not run_at.strip():
                return
            schedule = Schedule(uuid4().hex, name.strip(), prompt.strip(), run_at=run_at.strip())
        workflow_id = None
        workflows = self.mission_store.list_workflows()
        if workflows:
            choices = ["Vanlig task"] + [f"Workflow: {workflow.name}" for workflow in workflows]
            selected, accepted = QInputDialog.getItem(self, "New schedule", "Run:", choices, 0, False)
            if not accepted:
                return
            if selected != choices[0]:
                workflow_id = workflows[choices.index(selected) - 1].id
        agents = self.mission_store.list_agents()
        agent_id = None
        if agents:
            labels = ["Arqen default"] + [f"{agent.name} — {agent.role}" for agent in agents if agent.enabled]
            selected, accepted = QInputDialog.getItem(self, "New schedule", "Agent:", labels, 0, False)
            if not accepted:
                return
            if selected != labels[0]:
                agent_id = next(agent.id for agent in agents if f"{agent.name} — {agent.role}" == selected)
            schedule = Schedule(schedule.id, schedule.name, schedule.prompt, agent_id, schedule.cron, schedule.run_at, True, schedule.created_at, None, workflow_id)
        elif workflow_id:
            schedule = Schedule(schedule.id, schedule.name, schedule.prompt, None, schedule.cron, schedule.run_at, True, schedule.created_at, None, workflow_id)
        self.mission_store.save_schedule(schedule)
        self.refresh_mission_schedules()

    def _toggle_mission_schedule(self) -> None:
        item = self.mission_schedules.currentItem()
        if item is None:
            return
        schedule_id = item.data(Qt.ItemDataRole.UserRole)
        schedule = next((item for item in self.mission_store.list_schedules() if item.id == schedule_id), None)
        if schedule is not None:
            self.mission_store.set_schedule_enabled(schedule.id, not schedule.enabled)
            self.refresh_mission_schedules()

    def refresh_mission_agents(self) -> None:
        self.mission_agents.clear()
        for agent in self.mission_store.list_agents():
            status = self.mission_runner.runtime_status(agent.id)
            item = QListWidgetItem(f"[{status['status'].upper()}] {agent.name} // {agent.runtime}")
            item.setData(Qt.ItemDataRole.UserRole, agent.id)
            tools = ", ".join(agent.allowed_tools) or "inga verktyg"
            approvals = ", ".join(agent.approval_tools) or "inga"
            item.setToolTip(f"{status.get('detail', status.get('status', ''))}\nAllowed tools: {tools}\nRequires approval: {approvals}")
            self.mission_agents.addItem(item)

    def _create_mission_agent(self) -> None:
        agent_id, accepted = QInputDialog.getText(self, "New agent", "ID:")
        if not accepted or not agent_id.strip():
            return
        name, accepted = QInputDialog.getText(self, "New agent", "Name:")
        if not accepted or not name.strip():
            return
        role, accepted = QInputDialog.getText(self, "New agent", "Role:")
        if not accepted or not role.strip():
            return
        runtime, accepted = QInputDialog.getItem(self, "New agent", "Runtime:", ["arqen", "hermes"], 0, False)
        if not accepted:
            return
        available = [item["name"] for item in self.engine.tools.describe()]
        tools_text, accepted = QInputDialog.getText(
            self, "New agent", f"Allowed tools, comma-separated (available: {', '.join(available)}):"
        )
        if not accepted:
            return
        allowed_tools = tuple(item.strip() for item in tools_text.split(",") if item.strip())
        unknown = sorted(set(allowed_tools) - set(available))
        if unknown:
            QMessageBox.warning(self, "Mission Control", f"Okända verktyg: {', '.join(unknown)}")
            return
        approvals_text, accepted = QInputDialog.getText(self, "New agent", "Tools requiring approval (comma-separated):")
        if not accepted:
            return
        approval_tools = tuple(value.strip() for value in approvals_text.split(",") if value.strip())
        invalid_approvals = sorted(set(approval_tools) - set(allowed_tools))
        if invalid_approvals:
            QMessageBox.warning(self, "Mission Control", "Approval tools must be included in the allowlist.")
            return
        self.mission_store.save_agent(Agent(agent_id.strip(), name.strip(), role.strip(), runtime, True, allowed_tools, approval_tools))
        self.refresh_mission_agents()

    def _toggle_mission_agent(self) -> None:
        item = self.mission_agents.currentItem()
        if item is None:
            return
        agent_id = item.data(Qt.ItemDataRole.UserRole)
        agent = self.mission_store.get_agent(agent_id)
        if agent is None:
            return
        self.mission_store.save_agent(Agent(agent.id, agent.name, agent.role, agent.runtime, not agent.enabled))
        self.refresh_mission_agents()

    def _edit_mission_agent(self) -> None:
        item = self.mission_agents.currentItem()
        if item is None:
            return
        agent = self.mission_store.get_agent(item.data(Qt.ItemDataRole.UserRole))
        if agent is None:
            return
        name, accepted = QInputDialog.getText(self, "Edit agent", "Name:", text=agent.name)
        if not accepted or not name.strip():
            return
        role, accepted = QInputDialog.getText(self, "Edit agent", "Role:", text=agent.role)
        if not accepted or not role.strip():
            return
        runtime, accepted = QInputDialog.getItem(self, "Redigera agent", "Runtime:", ["arqen", "hermes"], max(0, ["arqen", "hermes"].index(agent.runtime)), False)
        if not accepted:
            return
        current_tools = ", ".join(agent.allowed_tools)
        tools_text, accepted = QInputDialog.getText(self, "Edit agent", "Allowed tools:", text=current_tools)
        if not accepted:
            return
        available = {entry["name"] for entry in self.engine.tools.describe()}
        allowed_tools = tuple(value.strip() for value in tools_text.split(",") if value.strip())
        unknown = sorted(set(allowed_tools) - available)
        if unknown:
            QMessageBox.warning(self, "Mission Control", f"Okända verktyg: {', '.join(unknown)}")
            return
        approvals_text, accepted = QInputDialog.getText(self, "Redigera agent", "Verktyg som kräver approval:", text=", ".join(agent.approval_tools))
        if not accepted:
            return
        approval_tools = tuple(value.strip() for value in approvals_text.split(",") if value.strip())
        if set(approval_tools) - set(allowed_tools):
            QMessageBox.warning(self, "Mission Control", "Approval-verktyg måste finnas i allowlisten.")
            return
        self.mission_store.save_agent(Agent(agent.id, name.strip(), role.strip(), runtime, agent.enabled, allowed_tools, approval_tools))
        self.refresh_mission_agents()

    def refresh_mission_tasks(self) -> None:
        if not hasattr(self, "mission_tasks"):
            return
        self.mission_tasks.clear()
        for task in self.mission_store.list_tasks():
            agent = self.mission_store.get_agent(task.agent_id) if task.agent_id else None
            owner = f" // {agent.name}" if agent else ""
            item = QListWidgetItem(f"[{task.status.upper()}] {task.title}{owner}")
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            self.mission_tasks.addItem(item)

    def refresh_mission_approvals(self) -> None:
        self.mission_approvals.clear()
        for approval in self.mission_store.list_approvals("pending"):
            item = QListWidgetItem(f"{approval.action} [{approval.task_id[:8]}]")
            item.setData(Qt.ItemDataRole.UserRole, approval.id)
            self.mission_approvals.addItem(item)

    def _decide_mission_approval(self, status: str) -> None:
        item = self.mission_approvals.currentItem()
        if item is None:
            return
        approval_id = item.data(Qt.ItemDataRole.UserRole)
        self.mission_store.decide_approval(approval_id, status)
        approval = self.mission_store.get_approval(approval_id)
        if status == "approved" and approval is not None:
            try:
                self.mission_runner.resume(approval.task_id)
            except Exception as exc:
                QMessageBox.warning(self, "Mission Control", str(exc))
        self.refresh_mission_tasks()
        self.refresh_mission_agents()
        self.refresh_mission_approvals()
        self._show_mission_task()

    def _selected_mission_task(self) -> Task | None:
        item = self.mission_tasks.currentItem()
        return self.mission_store.get_task(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _show_mission_task(self) -> None:
        task = self._selected_mission_task()
        if task is None:
            return
        events = self.mission_store.list_events(task.id)
        agent = self.mission_store.get_agent(task.agent_id) if task.agent_id else None
        agent_label = agent.name if agent else "Arqen default"
        source = task.schedule_id or "manuell"
        lines = [f"{task.title}\nStatus: {task.status}\nAgent: {agent_label}\nSource: {source}\nAttempts: {task.attempts}/{task.max_attempts}\nError: {task.error or 'none'}\n\n{task.prompt}", "", "Events:"]
        lines.extend(f"{event.created_at}  {event.kind}: {event.message}" for event in events)
        self.mission_details.setPlainText("\n".join(lines))

    def _create_mission_task(self) -> None:
        title, accepted = QInputDialog.getText(self, "New Mission Control task", "Title:")
        if not accepted or not title.strip():
            return
        prompt, accepted = QInputDialog.getMultiLineText(self, "New Mission Control task", "Task:")
        if not accepted or not prompt.strip():
            return
        agents = self.mission_store.list_agents()
        agent_id = None
        if agents:
            labels = ["No agent (Arqen default)"] + [f"{agent.name} — {agent.role}" for agent in agents if agent.enabled]
            selected, accepted = QInputDialog.getItem(self, "Tilldela agent", "Agent:", labels, 0, False)
            if not accepted:
                return
            if selected != labels[0]:
                agent_id = next(agent.id for agent in agents if f"{agent.name} — {agent.role}" == selected)
        task = Task.create(title.strip(), prompt.strip(), agent_id=agent_id)
        self.mission_store.save_task(task)
        from arqen.mission import Event
        self.mission_store.add_event(Event.create(task.id, "created", "Task created"))
        self.refresh_mission_tasks()

    def _run_mission_task(self) -> None:
        task = self._selected_mission_task()
        if task is None:
            return
        if getattr(self, "mission_thread", None) is not None and self.mission_thread.isRunning():
            return
        self.mission_thread = QThread(self)
        self.mission_worker = MissionWorker(self.mission_runner, task.id)
        self.mission_worker.moveToThread(self.mission_thread)
        self.mission_thread.started.connect(self.mission_worker.run)
        self.mission_worker.finished.connect(self._mission_finished)
        self.mission_worker.failed.connect(self._mission_failed)
        self.mission_worker.finished.connect(self.mission_thread.quit)
        self.mission_worker.failed.connect(self.mission_thread.quit)
        self.mission_thread.finished.connect(self.mission_worker.deleteLater)
        self.mission_thread.finished.connect(self.mission_thread.deleteLater)
        self.mission_thread.finished.connect(self._mission_thread_finished)
        self.mission_tasks.setEnabled(False)
        self.mission_details.setPlainText(f"{task.title}\nStatus: RUNNING\n\nArqen is working...")
        self.mission_thread.start()

    def _retry_mission_task(self) -> None:
        task = self._selected_mission_task()
        if task is None or task.status != "failed":
            return
        if not self.mission_store.retry_task(task.id):
            QMessageBox.information(self, "Mission Control", "The task has reached its maximum attempts.")
            return
        self.refresh_mission_tasks()
        self._show_mission_task()

    def _mission_finished(self, result: str) -> None:
        self.refresh_mission_tasks()
        self.refresh_mission_agents()
        self._show_mission_task()

    def _mission_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Mission Control", message)
        self.refresh_mission_tasks()
        self._show_mission_task()

    def _mission_thread_finished(self) -> None:
        self.mission_tasks.setEnabled(True)
        self.mission_thread = None
        self.mission_worker = None

    def show_session_menu(self, position) -> None:
        item = self.session_list.itemAt(position)
        if item is None:
            return
        self.session_list.setCurrentItem(item)
        menu = QMenu(self)
        open_action = menu.addAction("Öppna")
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Ta bort")
        selected = menu.exec(self.session_list.viewport().mapToGlobal(position))
        if selected == open_action:
            self.load_selected_session()
        elif selected == rename_action:
            self.rename_selected_session()
        elif selected == delete_action:
            self.delete_selected_session()

    def _create_visualization_dock(self) -> None:
        self.visualization_dock = QDockWidget("ARQEN VOICE", self)
        self.visualization_dock.setObjectName("voiceVisualizationDock")
        self.visualization_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.visualization_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        image_path = data_dir() / "generated" / "Arqen Desktop Voice_2.png"
        visualization = VoiceVisualizationWidget(image_path)
        self.visualization_dock.setWidget(visualization)
        set_audio_level_callback(visualization.set_audio_level)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.visualization_dock)
        self.visualization_dock.setMinimumSize(300, 240)
        self.visualization_dock.resize(400, 320)
        self.visualization_dock.setFloating(True)
        self.visualization_dock.installEventFilter(self)
        self._apply_placement("voice_visualization", self.visualization_dock, 300, 240)

    def _create_stats_dock(self) -> None:
        self.stats_dock = QDockWidget("ARQEN STATS", self)
        self.stats_dock.setObjectName("statsDock")
        self.stats_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.stats_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.stats_panel = StatsPanelWidget()
        self.stats_dock.setWidget(self.stats_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.stats_dock)
        self.stats_dock.setMinimumSize(240, 300)
        self.stats_dock.resize(280, 340)
        self.stats_dock.setFloating(True)
        self.stats_dock.installEventFilter(self)
        self._apply_placement("stats_panel", self.stats_dock, 240, 300)
        self.refresh_stats_panel()

    def refresh_stats_panel(self) -> None:
        panel = getattr(self, "stats_panel", None)
        if panel is None:
            return
        panel.update_usage(
            self.engine.session_usage,
            self.provider_metrics.totals(),
            self.engine.turn_usage,
            self.last_response_ms,
        )

    @staticmethod
    def _on_a_connected_screen(x: int, y: int) -> bool:
        from PyQt6.QtWidgets import QApplication

        return any(screen.geometry().contains(x, y) for screen in QApplication.screens())

    def _store_placement(self, key: str, widget) -> None:
        settings = QSettings("Arqen", "Arqen Desktop")
        settings.setValue(f"{key}_position", [widget.pos().x(), widget.pos().y()])
        settings.setValue(f"{key}_size", [widget.width(), widget.height()])

    def _apply_placement(self, key: str, widget, min_width: int, min_height: int) -> bool:
        """Put ``widget`` back where it was, or leave it to Qt.

        Position and size are stored plainly rather than through
        ``saveGeometry``: that format also carries the screen layout and frame
        margins it was recorded with, and reconciling those on restore moved
        the window every time.  A position on a monitor that is no longer
        attached is ignored, so nothing ends up stranded off the desktop.
        """
        settings = QSettings("Arqen", "Arqen Desktop")
        position = settings.value(f"{key}_position")
        size = settings.value(f"{key}_size")
        if position is None or size is None:
            return False
        try:
            x, y = (int(value) for value in position)
            width, height = (int(value) for value in size)
        except (TypeError, ValueError):
            return False
        if width < min_width or height < min_height or not self._on_a_connected_screen(x, y):
            return False
        widget.resize(width, height)
        widget.move(x, y)
        return True

    def _restore_window_geometry(self) -> None:
        """Open on the screen the window was last closed on, not wherever Windows puts it."""
        self.geometry_restored = self._apply_placement("main_window", self, 400, 300)

    def closeEvent(self, event) -> None:
        self._store_placement("main_window", self)
        for attribute, key in self._DOCK_GEOMETRY_KEYS.items():
            dock = getattr(self, attribute, None)
            if dock is not None and dock.isFloating():
                self._store_placement(key, dock)
        super().closeEvent(event)

    _DOCK_GEOMETRY_KEYS = {
        "visualization_dock": "voice_visualization",
        "stats_dock": "stats_panel",
    }

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
            for attribute, key in self._DOCK_GEOMETRY_KEYS.items():
                dock = getattr(self, attribute, None)
                if watched is dock and dock.isFloating():
                    self._store_placement(key, dock)
                    break
        return super().eventFilter(watched, event)

    def send_message(self) -> None:
        prompt = self.input.text().strip()
        if not prompt:
            return
        self.append_message("DU", prompt, CyberpunkGreenTheme.accent)
        # Voice/text confirmations should resolve the visible confirmation
        # dialog instead of being sent back to the model as a new prompt.
        if getattr(self.engine.executor, "_pending", None) is not None:
            normalized = re.sub(r"[^a-zåäö0-9 ]", " ", prompt.casefold())
            normalized = " ".join(normalized.split())
            affirmative = (
                normalized in {"ja", "japp", "yes", "bekräfta", "bekrafta", "kör", "kor"}
                or normalized.startswith(("ja ", "japp ", "yes ", "bekräfta ", "bekrafta ", "kör ", "kor "))
                or "öppna den" in normalized
                or "oppna den" in normalized
                or "jag öppnar" in normalized
                or "jag oppnar" in normalized
            )
            negative = normalized in {"nej", "no", "avbryt", "ångra", "angra"} or normalized.startswith(
                ("nej ", "no ", "avbryt ")
            )
            self.input.clear()
            if affirmative or negative:
                self._loading_timer.stop()
                self.resolve_confirmation(affirmative)
                return
        self._streaming_displayed = False
        self._stream_candidate = ""
        self.input.clear()
        self._loading_phase = 0
        self._loading_timer.start()
        self._animate_loading()
        self.input.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._cancel_requested = False
        self.engine.should_cancel = lambda: self._cancel_requested
        self.thread = QThread(self)
        self.worker = ResponseWorker(self.engine, prompt)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.response_finished)
        self.worker.failed.connect(self.response_failed)
        self.worker.cancelled.connect(self.response_cancelled)
        self.worker.tool_requested.connect(self.show_tool_request)
        self.worker.confirmation_required.connect(self.show_confirmation)
        self.worker.partial.connect(self.show_partial_response)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.response_thread_finished)
        self.thread.start()

    def provider_status(self, state: str = "READY", elapsed_ms: float | None = None) -> str:
        provider = getattr(self.engine.provider, "provider_name", self.provider_label)
        model = getattr(self.engine.provider, "model", "")
        profile = {"private": "LOCAL - OLLAMA", "fast": "FAST", "important": "IMPORTANT", "creative": "CREATIVE"}.get(
            self.profile_name,
            {"local": "PRIVATE", "openrouter": "FAST", "openai": "IMPORTANT"}.get(provider.lower(), "CUSTOM"),
        )
        details = f"PROFILE: {profile} // {provider.upper()} / {model}" if model else f"PROFILE: {profile} // {provider.upper()}"
        if getattr(self.engine.provider, "fallback_used", False):
            details = f"FALLBACK // {details}"
            reason = getattr(self.engine.provider, "fallback_reason", "")
            if reason:
                details += f" // {reason}"
        suffix = f" // {elapsed_ms / 1000:.1f}s" if elapsed_ms is not None else ""
        return f"{state} // {details}{suffix}"

    def set_status(self, text: str) -> None:
        upper = text.upper()
        color = CyberpunkGreenTheme.muted
        if "ERROR" in upper:
            color = CyberpunkGreenTheme.danger
        elif "FALLBACK" in upper:
            color = "#ffad4d"
        elif any(name in upper for name in ("OPENAI", "OPENROUTER", "GEMINI", "CLAUDE")):
            color = "#75bfff"
        elif "READY" in upper or "LOCAL" in upper:
            color = CyberpunkGreenTheme.accent
        self.status.setStyleSheet(f"color: {color}; letter-spacing: 1px;")
        self.status.setText(text)

    def response_finished(self, result: str, elapsed_ms: float) -> None:
        self._loading_timer.stop()
        # Nothing more is coming, so anything still waiting on a closing
        # marker has to be shown as it stands.
        self._flush_pending_text()
        self.last_response_ms = elapsed_ms
        active_provider = getattr(self.engine.provider, "provider_name", self.provider_label)
        active_model = getattr(self.engine.provider, "model", "")
        fallback_used = getattr(self.engine.provider, "fallback_used", False)
        self.provider_metrics.record(
            active_provider, active_model, elapsed_ms, True, fallback_used, self.engine.turn_usage
        )
        if fallback_used:
            self.fallback_count += 1
        if not self._streaming_displayed:
            self.append_message("ARQEN", result, CyberpunkGreenTheme.text)
        else:
            self.output.append("")
        self.voice_button.setText("🔊" if self.engine.voice_enabled else "🔇")
        if self.engine.last_response_speakable:
            from arqen.tools.speech import SpeakTextTool
            self.stop_button.setEnabled(True)
            threading.Thread(
                target=lambda: SpeakTextTool().run({"text": result}),
                daemon=True,
                name="arqen-auto-speech",
            ).start()
            QTimer.singleShot(250, self._refresh_speech_stop_state)
        self.set_status(self.provider_status("READY // RESPONSE COMPLETE", elapsed_ms))
        self.refresh_stats_panel()
        self.refresh_sessions()

    def _end_streaming_block(self) -> None:
        """Close the current ARQEN block so the next chunk starts a new one.

        A tool call splits one turn into several streamed passages.  Without
        this the text that follows the tool is inserted at the end of the
        document, which is the TOOL line itself.
        """
        self._flush_pending_text()
        self._streaming_displayed = False
        self._stream_candidate = ""

    def _flush_pending_text(self) -> None:
        """Show text held back waiting for a closing marker that never came."""
        pending, self._stream_candidate = self._stream_candidate, ""
        if pending and self._streaming_displayed:
            self._insert_streamed(strip_emphasis(pending))

    def _insert_streamed(self, text: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.output.setTextCursor(cursor)
        self.output.insertPlainText(text)

    def show_partial_response(self, text: str) -> None:
        if getattr(self, "_cancel_requested", False):
            return
        self._stream_candidate += text
        candidate = self._stream_candidate.lstrip()
        if candidate.startswith("{") or candidate.startswith("<tool_call"):
            return
        ready, self._stream_candidate = split_pending(self._stream_candidate)
        if not ready:
            return
        if not self._streaming_displayed:
            self.output.append("<b>ARQEN:</b>")
            self._streaming_displayed = True
        self._insert_streamed(ready)

    def _refresh_speech_stop_state(self) -> None:
        try:
            from arqen.tools.speech import _speech_done
            if not _speech_done.is_set():
                self.stop_button.setEnabled(True)
                QTimer.singleShot(250, self._refresh_speech_stop_state)
                return
            thread = getattr(self, "thread", None)
            if thread is None or not thread.isRunning():
                self.stop_button.setEnabled(False)
        except RuntimeError:
            # Qt object may have been deleted during thread cleanup.
            return

    def response_failed(self, message: str) -> None:
        self._loading_timer.stop()
        self.provider_metrics.record(
            getattr(self.engine.provider, "provider_name", self.provider_label),
            getattr(self.engine.provider, "model", ""),
            0.0,
            False,
            getattr(self.engine.provider, "fallback_used", False),
            self.engine.turn_usage,
        )
        self.append_message("FEL", message, CyberpunkGreenTheme.danger)
        self.refresh_stats_panel()
        self.set_status(self.provider_status("ERROR // REQUEST FAILED"))

    def response_cancelled(self) -> None:
        self._loading_timer.stop()
        self.set_status(self.provider_status("STOPPED // RESPONSE DISCARDED"))

    def _animate_loading(self) -> None:
        self._loading_phase = (self._loading_phase + 1) % 4
        dots = "." * self._loading_phase
        self.set_status(self.provider_status(f"WORKING // PROCESSING REQUEST{dots}"))

    def response_thread_finished(self) -> None:
        self.worker.deleteLater()
        self.thread.deleteLater()
        self.input.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.input.setFocus()

    def stop_response(self) -> None:
        try:
            from arqen.tools.speech import stop_speech
            stop_speech()
        except Exception:
            pass
        try:
            thread = getattr(self, "thread", None)
            running = thread is not None and thread.isRunning()
            confirm_thread = getattr(self, "confirm_thread", None)
            if not running and confirm_thread is not None:
                thread, running = confirm_thread, confirm_thread.isRunning()
            if running:
                # The flag stops the provider's stream loop and the engine's
                # tool loop; requestInterruption is kept for the worker's own
                # final check.
                self._cancel_requested = True
                thread.requestInterruption()
            self.set_status(self.provider_status("STOPPED // RESPONSE DISCARDED" if running else "READY"))
            self.stop_button.setEnabled(False)
        except RuntimeError:
            # The response thread may already have been deleted by Qt.
            return

    def toggle_voice_mode(self) -> None:
        self.engine.voice_enabled = not self.engine.voice_enabled
        if self.engine.voice_enabled:
            self.voice_button.setText("🔊")
            self.set_status(self.provider_status("VOICE // ENABLED"))
        else:
            try:
                from arqen.tools.speech import stop_speech
                stop_speech()
            except Exception:
                pass
            self.voice_button.setText("🔇")
            self.set_status(self.provider_status("VOICE // DISABLED"))

    def toggle_microphone(self) -> None:
        if self.microphone.recording:
            self.microphone.stop()
            self.mic_button.setText("🎙")
            self.mic_button.setToolTip("Start microphone recording")
        else:
            if self.microphone.start():
                self.mic_button.setText("⏺")
                self.mic_button.setToolTip("Stop microphone recording")

    @pyqtSlot(str)
    def _handle_microphone_result(self, text: str) -> None:
        """Put a transcription in the composer and submit it automatically."""
        cleaned = text.strip()
        if not cleaned:
            return
        self.input.setText(cleaned)
        QTimer.singleShot(100, self.send_message)

    def show_tool_request(self, name: str) -> None:
        self.set_status(f"TOOL // {name.upper()}")
        self._end_streaming_block()
        self.append_message("TOOL", name, CyberpunkGreenTheme.muted)

    def append_message(self, sender: str, content: str, color: str) -> None:
        content = re.sub(r"\\\\?n", "\n", content)
        content = re.sub(r"\\\r?\n", "\n", content)
        content = content.replace("\\*", "*").replace("\\-", "-")
        safe_content = self.render_content(content)
        self.output.append(
            f"<div style='margin:6px 0;'><b style='color:{color}'>{sender}:</b> "
            f"<span style='color:{CyberpunkGreenTheme.text}'>{safe_content}</span></div>"
        )

    @staticmethod
    def render_content(content: str) -> str:
        lines = content.splitlines() or [content]
        rendered = []
        table_rows = []

        def flush_table() -> None:
            if not table_rows:
                return
            rendered.append("<table style='border-collapse:collapse; margin:4px 0;'>")
            for index, row in enumerate(table_rows):
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if index == 1 and all(set(cell) <= {"-", ":", " "} for cell in cells):
                    continue
                tag = "th" if index == 0 else "td"
                cells = [re.sub(r"`([^`]+)`", r"<code style='color:#58f28b'>\1</code>", cell) for cell in cells]
                cells = [re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", cell) for cell in cells]
                rendered.append("<tr>" + "".join(
                    f"<{tag} style='border:1px solid #244132; padding:4px 8px;'>{cell}</{tag}>" for cell in cells
                ) + "</tr>")
            rendered.append("</table>")
            table_rows.clear()

        for line in lines:
            if line.strip().startswith("|"):
                table_rows.append(line)
                continue
            flush_table()
            if re.fullmatch(r"\s*([-_*])\1\1+\s*", line):
                continue
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            escaped = re.sub(r"^#{1,2} (.+)$", r"<b style='font-size:16px'>\1</b>", escaped)
            escaped = re.sub(r"^#{3,6} (.+)$", r"<b>\1</b>", escaped)
            escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
            escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
            escaped = re.sub(r"`([^`]+)`", r"<code style='color:#58f28b'>\1</code>", escaped)
            escaped = re.sub(r"^- ", "• ", escaped)
            rendered.append(escaped + "<br>")
        flush_table()
        result = "".join(rendered)
        return result[:-4] if result.endswith("<br>") else result

    def refresh_sessions(self) -> None:
        self.session_list.clear()
        selector = getattr(self, "chat_session_selector", None)
        if selector is not None:
            selector.blockSignals(True)
            selector.clear()
        for session in self.engine.session_store.list_sessions():
            item = QListWidgetItem(session.title)
            item.setData(Qt.ItemDataRole.UserRole, session.session_id)
            self.session_list.addItem(item)
            if selector is not None:
                selector.addItem(session.title, session.session_id)
        if selector is not None:
            current_id = self.engine.session.session_id if self.engine.session else None
            current_index = selector.findData(current_id)
            if current_index >= 0:
                selector.setCurrentIndex(current_index)
            selector.blockSignals(False)

    def _load_selected_chat_from_bar(self, index: int) -> None:
        selector = getattr(self, "chat_session_selector", None)
        if selector is None:
            return
        session_id = selector.itemData(index)
        if not session_id:
            return
        for row in range(self.session_list.count()):
            item = self.session_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.session_list.setCurrentItem(item)
                self.load_selected_session()
                return

    def create_new_session(self) -> None:
        title, accepted = QInputDialog.getText(self, "New chat", "Title:")
        if not accepted:
            return
        self.engine.new_session(title.strip() or "New chat")
        self.output.clear()
        self.status.setText("READY // NEW SESSION")
        self.refresh_sessions()

    def load_selected_session(self) -> None:
        item = self.session_list.currentItem()
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        matches = [s for s in self.engine.session_store.list_sessions() if s.session_id == session_id]
        if not matches:
            return
        session = self.engine.load_session(matches[0].session_id)
        self.output.clear()
        for message in session.messages:
            if message.role == "user":
                self.append_message("DU", message.content, CyberpunkGreenTheme.accent)
            elif message.role == "assistant":
                self.append_message("ARQEN", message.content, CyberpunkGreenTheme.text)
            elif message.role == "tool":
                self.append_message("TOOL RESULT", message.content, CyberpunkGreenTheme.muted)
                self.show_generated_image(message.content)
        self.status.setText("READY // SESSION LOADED")

    def selected_session(self):
        item = self.session_list.currentItem()
        if item is None:
            return None
        session_id = item.data(Qt.ItemDataRole.UserRole)
        matches = [s for s in self.engine.session_store.list_sessions() if s.session_id == session_id]
        return matches[0] if matches else None

    def rename_selected_session(self) -> None:
        session = self.selected_session()
        if session is None:
            return
        title, accepted = QInputDialog.getText(self, "Rename", "New name:", text=session.title)
        if accepted and title.strip():
            session.title = title.strip()
            self.engine.session_store.save(session)
            if session.session_id == self.engine.session.session_id:
                self.engine.session.title = session.title
            self.refresh_sessions()

    def delete_selected_session(self) -> None:
        session = self.selected_session()
        if session is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete chat",
            f"Vill du ta bort '{session.title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.engine.session_store.delete(session.session_id)
        if session.session_id == self.engine.session.session_id:
            self.engine.new_session()
            self.output.clear()
        self.refresh_sessions()

    def show_confirmation(self, name: str, arguments: dict | None = None) -> None:
        self.set_status(f"CONFIRMATION REQUIRED // {name.upper()}")
        details = ""
        if arguments:
            details = " | " + ", ".join(
                f"{key}: {str(value)[:160]}" for key, value in arguments.items()
            )
        self._end_streaming_block()
        self.append_message("CONFIRM", f"{name}{details}", CyberpunkGreenTheme.accent)
        self.confirm_button.setVisible(True)
        self.cancel_button.setVisible(True)
        self.confirm_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def resolve_confirmation(self, accepted: bool) -> None:
        self.confirm_button.setVisible(False)
        self.cancel_button.setVisible(False)
        if not accepted:
            result = self.engine.confirm_pending_tool(False)
            self.output.append(f"<b>ARQEN:</b> {result}")
            self.set_status("READY // CONFIRMATION CANCELLED")
            return
        self.set_status(self.provider_status("WORKING // RUNNING CONFIRMED TOOL"))
        self._end_streaming_block()
        self._cancel_requested = False
        self.engine.should_cancel = lambda: self._cancel_requested
        self.stop_button.setEnabled(True)
        self.confirm_thread = QThread(self)
        self.confirm_worker = ConfirmationWorker(self.engine)
        self.confirm_worker.moveToThread(self.confirm_thread)
        self.confirm_thread.started.connect(self.confirm_worker.run)
        self.confirm_worker.finished.connect(self.confirmation_finished)
        self.confirm_worker.failed.connect(self.confirmation_failed)
        self.confirm_worker.tool_requested.connect(self.show_tool_request)
        self.confirm_worker.confirmation_required.connect(self.show_confirmation)
        self.confirm_worker.partial.connect(self.show_partial_response)
        self.confirm_worker.finished.connect(self.confirm_thread.quit)
        self.confirm_worker.failed.connect(self.confirm_thread.quit)
        self.confirm_thread.finished.connect(self.confirm_worker.deleteLater)
        self.confirm_thread.finished.connect(self.confirm_thread.deleteLater)
        self.confirm_thread.start()

    def confirmation_finished(self, result: str) -> None:
        if not self._streaming_displayed:
            self.output.append(f"<b>ARQEN:</b> {result}")
        self._end_streaming_block()
        self.stop_button.setEnabled(False)
        # The model's closing words rarely repeat the tool's own output, so the
        # image path is taken from the tool result rather than from the reply.
        self.show_generated_image(self.engine.last_tool_output or result)
        self.refresh_stats_panel()
        self.set_status("READY // CONFIRMATION RESOLVED")

    def show_generated_image(self, result: str) -> None:
        image_match = re.search(r"Bild skapad:\s*(.+)$", result)
        if image_match:
            image_path = Path(image_match.group(1).strip()).resolve()
            if image_path.exists():
                image_url = QUrl.fromLocalFile(str(image_path)).toString()
                self.output.append(f"<div style='margin:8px 0;'><img src='{image_url}' width='640'></div>")

    def confirmation_failed(self, message: str) -> None:
        self.append_message("FEL", message, CyberpunkGreenTheme.danger)
        self.set_status("ERROR // CONFIRMATION FAILED")

    def open_settings(self) -> None:
        config = load_provider_config()
        dialog = QDialog(self)
        dialog.setWindowTitle("Arqen Settings")
        dialog.setMinimumSize(960, 760)
        dialog.setStyleSheet(CyberpunkGreenTheme.stylesheet())
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(20, 18, 20, 18)
        tabs = QTabWidget()
        profile_tab = QWidget()
        provider_tab = QWidget()
        workspace_tab = QWidget()
        fallback_tab = QWidget()
        stats_tab = QWidget()
        profile_form = QFormLayout(profile_tab)
        provider_form = QFormLayout(provider_tab)
        workspace_form = QFormLayout(workspace_tab)
        fallback_form = QFormLayout(fallback_tab)
        for tab_form in (profile_form, provider_form, workspace_form, fallback_form):
            tab_form.setContentsMargins(10, 12, 10, 12)
            tab_form.setHorizontalSpacing(18)
            tab_form.setVerticalSpacing(12)
        stats_layout = QVBoxLayout(stats_tab)
        stats_layout.setContentsMargins(10, 12, 10, 12)
        tabs.addTab(profile_tab, "Profile")
        tabs.addTab(provider_tab, "Provider")
        tabs.addTab(workspace_tab, "Arbetsyta")
        tabs.addTab(fallback_tab, "Fallback")
        tabs.addTab(stats_tab, "Statistik")
        dialog_layout.addWidget(tabs, 1)

        provider = QComboBox()
        provider_items = [("Local Ollama", "local"), ("Arqen Remote", "arqen-remote"), ("OpenAI", "openai"), ("OpenRouter", "openrouter"), ("Gemini", "gemini"), ("Claude", "claude"), ("Demo", "demo")]
        for label, value in provider_items:
            provider.addItem(label, value)
        provider.setCurrentIndex(max(0, provider.findData(config.name)))
        profile = QComboBox()
        profile.addItem("Private – Ollama", "private")
        profile.addItem("Fast – OpenRouter", "fast")
        profile.addItem("Viktigt – OpenAI", "important")
        profile.addItem("Kreativt arbete – OpenRouter", "creative")
        saved_profile = {"private": "private", "fast": "fast", "important": "important", "creative": "creative"}.get(config.profile_name, "")
        if saved_profile:
            profile.setCurrentIndex(profile.findData(saved_profile))
        profile_form.addRow("Profil", profile)
        profile_hint = QLabel()
        profile_hint.setWordWrap(True)
        profile_form.addRow("Beskrivning", profile_hint)
        profile_descriptions = {
            "private": "Local and private. Uses Ollama without cloud fallback.",
            "fast": "Fast everyday profile. Uses OpenRouter without automatic fallback.",
            "important": "For important tasks. Uses OpenAI without automatic fallback.",
            "creative": "For ideas, writing and creative workflows via Gemini.",
        }
        profile_hint.setText(profile_descriptions[profile.currentData()])
        profile.currentIndexChanged.connect(
            lambda _: profile_hint.setText(profile_descriptions[profile.currentData()])
        )
        model = QComboBox()
        model.setEditable(True)
        model.setMinimumWidth(520)
        model.addItem(f"[{config.name.upper()}] {config.model}", config.model)
        model_search = QLineEdit()
        model_search.setPlaceholderText("Search models...")
        provider_form.addRow("Search models", model_search)
        model_search.textChanged.connect(lambda text: self.filter_model_choices(model, text))
        model_search.returnPressed.connect(lambda: self.filter_model_choices(model, model_search.text()))
        base_url = QLineEdit(config.base_url)
        timeout = QLineEdit(str(config.timeout))
        api_key = QLineEdit(config.api_key)
        api_key.setEchoMode(QLineEdit.EchoMode.Password)
        provider_form.addRow("Provider", provider)
        provider_form.addRow("Modell", model)
        provider_form.addRow("URL", base_url)
        provider_form.addRow("API key", api_key)
        provider_form.addRow("Timeout", timeout)
        fallback_enabled = QCheckBox("Enable fallback on provider error")
        fallback_enabled.setChecked(config.fallback_enabled)
        fallback_provider = QComboBox()
        for label, value in provider_items:
            if value != config.name:
                fallback_provider.addItem(label, value)
        fallback_provider.setCurrentIndex(max(0, fallback_provider.findData(config.fallback_provider)))
        fallback_timeout = QLineEdit(str(config.fallback_timeout))
        fallback_form.addRow("Fallback", fallback_enabled)
        fallback_form.addRow("Reservprovider", fallback_provider)
        fallback_form.addRow("Fallback-timeout (s)", fallback_timeout)
        provider_info = QLabel(self.provider_overview(fallback_enabled.isChecked()))
        provider_info.setWordWrap(True)
        fallback_form.addRow("Providerstatus", provider_info)
        stats_button = QPushButton("VIEW PROVIDER STATISTICS")
        stats_button.setObjectName("secondaryButton")
        stats_button.clicked.connect(self.show_provider_metrics)
        stats_layout.addWidget(stats_button)
        reset_stats = QPushButton("RESET STATISTICS")
        reset_stats.setObjectName("secondaryButton")
        reset_stats.clicked.connect(self.reset_provider_metrics)
        stats_layout.addWidget(reset_stats)
        provider.currentIndexChanged.connect(
            lambda _: self.configure_provider_fields(provider.currentData(), model, base_url)
        )
        provider.currentIndexChanged.connect(lambda _: api_key.setText(load_api_key(provider.currentData())))
        self.configure_provider_fields(config.name, model, base_url)
        model.clear()
        model.addItem(f"[{config.name.upper()}] {config.model}", config.model)
        model.setCurrentText(config.model)

        # Quick profiles are presets: selecting one should apply its provider,
        # model and connection settings immediately.  Saving must not depend
        # on the user remembering a second "TILLÄMPA PROFIL" click.
        profile.currentIndexChanged.connect(
            lambda _: self.apply_provider_profile(
                profile.currentData(), provider, model, base_url, timeout, api_key,
                fallback_enabled, fallback_provider, fallback_timeout,
            )
        )

        apply_profile = QPushButton("TILLÄMPA PROFIL")
        apply_profile.setObjectName("secondaryButton")
        apply_profile.clicked.connect(
            lambda: self.apply_provider_profile(
                profile.currentData(), provider, model, base_url, timeout, api_key,
                fallback_enabled, fallback_provider, fallback_timeout,
            )
        )
        profile_form.addRow(apply_profile)

        workspace = QLineEdit(str(load_workspace_root()))
        workspace.setMinimumWidth(520)
        workspace_form.addRow("Arbetskatalog", workspace)
        browse = QPushButton("VÄLJ MAPP")
        browse.setObjectName("secondaryButton")
        browse.clicked.connect(lambda: self.choose_workspace(dialog, workspace))
        workspace_form.addRow(browse)
        workspace_hint = QLabel(
            "Mappen Arqen läser och skriver filer i. Den påverkar bara verktygen — "
            "settings, chats and memory remain inside the application "
            f"({APP_ROOT}). Lämna den tom för att använda programmets egen mapp."
        )
        workspace_hint.setWordWrap(True)
        workspace_form.addRow("Om", workspace_hint)

        refresh_models = QPushButton("FETCH MODELS")
        refresh_models.setObjectName("secondaryButton")
        refresh_models.clicked.connect(lambda: self.load_local_models(model, base_url.text(), api_key.text(), provider.currentData()))
        actions_layout = QHBoxLayout()
        actions_layout.addWidget(refresh_models)

        test_connection = QPushButton("TEST CONNECTION")
        test_connection.setObjectName("secondaryButton")
        test_connection.clicked.connect(
            lambda: self.test_provider_connection(provider.currentData(), model.currentData() or model.currentText(), base_url.text(), api_key.text())
        )
        actions_layout.addWidget(test_connection)

        save = QPushButton("SPARA")
        save.setObjectName("primaryButton")
        save.clicked.connect(
            lambda: self.save_settings(
                dialog,
                provider.currentData(),
                re.sub(r"^\[[^\]]+\]\s*", "", model.currentText()),
                base_url.text(),
                timeout.text(),
                api_key.text(),
                fallback_enabled.isChecked(),
                fallback_provider.currentData() or "",
                fallback_timeout.text(),
                profile.currentData(),
                workspace.text(),
            )
        )
        actions_layout.addWidget(save)
        dialog_layout.addLayout(actions_layout)
        for button in (stats_button, reset_stats, apply_profile, refresh_models, test_connection, browse, save):
            button.setAutoDefault(False)
            button.setDefault(False)
        dialog.exec()

    def apply_provider_profile(self, profile: str, provider: QComboBox, model: QComboBox, base_url: QLineEdit, timeout: QLineEdit, api_key: QLineEdit, fallback_enabled: QCheckBox, fallback_provider: QComboBox, fallback_timeout: QLineEdit) -> None:
        presets = {
            "private": ("local", "", "http://127.0.0.1:11434/v1", 60.0, False, ""),
            "fast": ("openrouter", "xiaomi/mimo-v2.6-pro", "https://openrouter.ai/api/v1", 120.0, False, ""),
            "important": ("openai", "gpt-5.6", "https://api.openai.com/v1", 120.0, False, ""),
            "creative": ("gemini", "gemini-3.1-flash-lite", "https://generativelanguage.googleapis.com/v1beta", 120.0, False, ""),
        }
        name, preset_model, url, wait, fallback, reserve = presets[profile]
        provider.setCurrentIndex(max(0, provider.findData(name)))
        self.configure_provider_fields(name, model, base_url)
        if preset_model:
            model.clear()
            model.addItem(f"[{name.upper()}] {preset_model}", preset_model)
            model.setCurrentText(preset_model)
        base_url.setText(url)
        timeout.setText(str(wait))
        api_key.setText(load_api_key(name))
        fallback_enabled.setChecked(fallback)
        fallback_provider.setCurrentIndex(max(0, fallback_provider.findData(reserve)))
        fallback_timeout.setText("10.0")

    def provider_overview(self, fallback_enabled: bool | None = None) -> str:
        provider = getattr(self.engine.provider, "provider_name", self.provider_label).upper()
        model = getattr(self.engine.provider, "model", "") or "unknown model"
        used = getattr(self.engine.provider, "fallback_used", False)
        if fallback_enabled is True and not used:
            fallback = "aktiverad, inte använd ännu"
        elif fallback_enabled is False:
            fallback = "avstängd"
        else:
            fallback = "används nu" if used else "inte aktiverad"
        elapsed = f"{self.last_response_ms / 1000:.1f} s" if self.last_response_ms is not None else "ingen mätning ännu"
        metrics = self.provider_metrics._load().get(f"{provider.lower()}/{model}", {})
        avg_ms = metrics.get("total_ms", 0) / metrics.get("requests", 1)
        return (
            f"Aktiv: {provider} / {model}\n"
            f"Fallback: {fallback}\n"
            f"Senaste svarstid: {elapsed}\n"
            f"Fallbackväxlingar: {self.fallback_count}\n"
            f"Historik: {metrics.get('requests', 0)} svar, genomsnitt {avg_ms / 1000:.1f} s"
        )

    def show_provider_metrics(self) -> None:
        metrics = self.provider_metrics._load()
        if not metrics:
            text = "Ingen providerstatistik finns ännu."
        else:
            rows = []
            sorted_metrics = sorted(
                metrics.items(),
                key=lambda pair: (pair[1].get("total_ms", 0) / pair[1].get("requests", 1)) if pair[1].get("requests", 0) else float("inf"),
            )
            for key, item in sorted_metrics:
                requests = item.get("requests", 0)
                average = item.get("total_ms", 0) / requests / 1000 if requests else 0
                success_rate = (item.get("successes", 0) / requests * 100) if requests else 0
                rows.append(
                    f"{key}\n"
                    f"  Svar: {requests} | Lyckade: {item.get('successes', 0)} | Fel: {item.get('errors', 0)} | Lyckandegrad: {success_rate:.0f}%\n"
                    f"  Genomsnitt: {average:.1f} s | Fallback: {item.get('fallbacks', 0)}"
                )
            text = "\n\n".join(rows)
        QMessageBox.information(self, "Providerstatistik", text)

    def reset_provider_metrics(self) -> None:
        answer = QMessageBox.question(
            self,
            "Nollställ statistik",
            "Vill du ta bort all sparad providerstatistik?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.provider_metrics.reset()
            QMessageBox.information(self, "Providerstatistik", "Providerstatistiken är nollställd.")

    def choose_workspace(self, dialog: QDialog, field: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(dialog, "Choose workspace", field.text() or str(APP_ROOT))
        if chosen:
            field.setText(str(Path(chosen)))

    def save_settings(self, dialog: QDialog, name: str, model: str, base_url: str, timeout: str, api_key: str, fallback_enabled: bool = False, fallback_provider: str = "", fallback_timeout: str = "10", profile_name: str = "", workspace: str = "") -> None:
        try:
            config = ProviderConfig(
                name=name,
                model=model.strip(),
                base_url=base_url.strip().rstrip("/"),
                timeout=float(timeout),
                api_key=api_key.strip(),
                fallback_enabled=fallback_enabled,
                fallback_provider=fallback_provider,
                fallback_timeout=float(fallback_timeout),
                profile_name=profile_name,
            )
            self.engine.provider = create_provider(config)
            save_provider_config(config)
            chosen = workspace.strip()
            if chosen and not Path(chosen).expanduser().is_dir():
                raise ValueError(f"Arbetskatalogen finns inte: {chosen}")
            save_workspace_root(chosen)
            self.provider_label = config.name
            self.profile_name = profile_name
            self.set_status(self.provider_status("READY // PROVIDER UPDATED"))
            dialog.accept()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(dialog, "Invalid settings", str(exc))

    @staticmethod
    def filter_model_choices(model_box: QComboBox, query: str) -> None:
        query = query.casefold().strip()
        current = model_box.currentText()
        for index in range(model_box.count()):
            model_box.view().setRowHidden(index, bool(query) and query not in model_box.itemText(index).casefold())
        if current:
            model_box.setEditText(current)

    def load_local_models(self, model_box: QComboBox, base_url: str, api_key: str = "", provider: str = "local") -> None:
        try:
            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            if provider == "claude":
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            elif provider == "gemini":
                url = f"{url}?key={api_key}"
                headers = {}
            request = Request(url, headers=headers)
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            models = [item.get("id") for item in data.get("data", []) if item.get("id")]
            if provider == "gemini":
                models = [item.get("name", "").removeprefix("models/") for item in data.get("models", []) if item.get("name")]
            if models:
                current = model_box.currentData() or model_box.currentText()
                model_box.clear()
                for model_id in models:
                    model_box.addItem(f"[{provider.upper()}] {model_id}", model_id)
                selected = models.index(current) if current in models else 0
                model_box.setCurrentIndex(selected)
        except Exception as exc:
            QMessageBox.warning(self, "Modeller kunde inte hämtas", str(exc))

    def configure_provider_fields(self, provider: str, model_box: QComboBox, base_url: QLineEdit) -> None:
        defaults = {
            "local": ("http://127.0.0.1:11434/v1", "qwen3:8b"),
            "arqen-remote": ("https://api.samidatools.com", "qwen3:4b"),
            "openai": ("https://api.openai.com/v1", "gpt-5"),
            "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"),
            "claude": ("https://api.anthropic.com/v1", "claude-sonnet-4-20250514"),
            "demo": ("", "demo"),
        }
        url, model = defaults.get(provider, (base_url.text(), model_box.currentText()))
        try:
            saved = json.loads((config_dir() / "arqen.json").read_text(encoding="utf-8"))
            profile = saved.get("providers", {}).get(provider, {})
            url = profile.get("base_url", url)
            model = profile.get("model", model)
            model = re.sub(r"^\[[^\]]+\]\s*", "", str(model))
        except (OSError, json.JSONDecodeError):
            pass
        base_url.setText(url)
        model_box.clear()
        model_box.addItem(f"[{provider.upper()}] {model}", model)
        model_box.setCurrentText(model)
        if provider in {"openai", "openrouter"}:
            model_box.setToolTip("Click FETCH MODELS to load provider models")
        else:
            model_box.setToolTip("Type or select a model for this provider")

    def test_provider_connection(self, provider: str, model: str, base_url: str, api_key: str = "") -> None:
        if provider == "demo":
            QMessageBox.information(self, "Connection OK", "The demo provider is available.")
            return
        try:
            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            if provider == "claude":
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            elif provider == "gemini":
                url = f"{url}?key={api_key}"
                headers = {}
            request = Request(url, headers=headers)
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            available = {item.get("id") for item in data.get("data", [])}
            if provider == "gemini":
                available = {
                    item.get("name", "").removeprefix("models/")
                    for item in data.get("models", [])
                    if item.get("name")
                }
            if model not in available:
                raise RuntimeError(f"Modellen finns inte hos providern: {model}")
            QMessageBox.information(self, "Connection OK", f"Provider responded and the model exists:\n{model}")
        except Exception as exc:
            QMessageBox.warning(self, "Connection failed", str(exc))

    @staticmethod
    def model_label(model_id: str) -> str:
        kind = "CLOUD" if model_id.lower().endswith(":cloud") else "LOCAL"
        return f"[{kind}] {model_id}"
