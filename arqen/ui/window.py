from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QPlainTextEdit,
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
    QScrollArea,
    QFileDialog,
    QDialogButtonBox,
)
from PyQt6.QtCore import QEvent, QObject, QSettings, QThread, QTimer, Qt, QUrl, QPoint, QPointF, QRectF, QSize, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from urllib.request import Request, urlopen
import json
import html
from dataclasses import replace as replace_dataclass
import math
import re
import threading
from types import SimpleNamespace
import time
from datetime import datetime, timezone
from pathlib import Path

from arqen.core.engine import ConversationEngine
from arqen.config.settings import (
    load_provider_config,
    save_provider_config,
    load_api_key,
    load_workspace_root,
    save_workspace_root,
)
from arqen.config import paths
from arqen.config.paths import APP_ROOT, config_dir, workspace_root
from arqen.providers.config import ProviderConfig
from arqen.providers.factory import create_provider
from arqen.tools.builtins import create_builtin_registry
from arqen.ui.strings import status_label, tr, tr_status
from arqen.ui.tool_catalog import CATEGORIES, ToolInfo, tool_info
from arqen.connectors import GrantState, all_connectors, grant_state, with_connector, without_connector
from arqen.connectors import store as connector_store
from arqen.core import chat_tools
from arqen.connectors.external import EXTERNAL
from arqen.connectors import mcp as mcp_servers
from arqen.ui.theme import CyberpunkGreenTheme, VoicePalette, load_voice_palette
from arqen.core.provider_metrics import ProviderMetrics
from arqen.core.memory_store import MemoryStore
from arqen.tools.speech import set_audio_level_callback
from arqen.tools.microphone import MicrophoneRecorder
from arqen.mission import Agent, MissionRunner, MissionStore, Schedule, Task, Workflow, WorkflowRunner, WorkflowStep
from arqen.mission.scheduler import MissionScheduler
from arqen.mission.scheduler_worker import SchedulerWorker
from arqen.mission.task_worker import TaskWorker
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


class ChatInput(QPlainTextEdit):
    """The message box: Enter sends, Shift+Enter starts a new line.

    It keeps the QLineEdit calls the window already uses (``text``,
    ``setText``, ``returnPressed``) and grows with its text up to a few lines,
    after which it scrolls.
    """

    returnPressed = pyqtSignal()
    MAX_LINES = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatInput")
        self.setTabChangesFocus(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().contentsChanged.connect(self._fit_height)
        self._fit_height()

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        self.moveCursor(self.textCursor().MoveOperation.End)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # A plain "\n": Qt's own Shift+Enter inserts a line separator
                # (U+2028) that would reach the model as an odd character.
                self.insertPlainText("\n")
            else:
                self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Wrapping depends on the width, so the height follows it.
        self._fit_height()

    def _fit_height(self) -> None:
        # Resizing calls this again; without the guard, and with a height taken
        # from the current geometry, the two fed each other until the stack ran out.
        if getattr(self, "_fitting", False):
            return
        self._fitting = True
        try:
            # With the plain-text layout the document height is counted in lines.
            lines = max(1, min(self.MAX_LINES, int(self.document().size().height())))
            text_height = lines * self.fontMetrics().lineSpacing() + 2 * self.document().documentMargin()
            margins = self.contentsMargins()
            viewport = self.viewportMargins()
            chrome = 2 * self.frameWidth() + margins.top() + margins.bottom() + viewport.top() + viewport.bottom()
            height = int(text_height + chrome)
            if height != self.height():
                self.setFixedHeight(height)
        finally:
            self._fitting = False


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


class ReflectionWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, run) -> None:
        super().__init__()
        self._run = run

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self._run())
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


class VoiceVisualizationWidget(QWidget):
    """Compact ring HUD for Arqen's voice: idle, listening, thinking and speaking.

    Everything is painted, so the colours follow ``VoicePalette`` and nothing
    depends on a generated image.  The window sets the base state; speaking is
    derived from the TTS audio level, because only playback knows when sound
    actually starts and stops.
    """

    STATES = ("idle", "listening", "thinking", "speaking")
    _LABELS = {"idle": "IDLE", "listening": "LISTENING", "thinking": "THINKING", "speaking": "SPEAKING"}
    # Short gaps between words must not make the ring flicker back to idle.
    _SPEECH_HOLD = 0.45

    audio_level_changed = pyqtSignal(float)
    input_level_changed = pyqtSignal(float)

    def __init__(self, palette: VoicePalette | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_colors = palette or VoicePalette()
        self._base_state = "idle"
        self._model_label = ""
        self._audio_level = 0.0
        self._input_level = 0.0
        self._level = 0.0
        self._last_speech_at = 0.0
        self._started = time.monotonic()
        self._clock = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.audio_level_changed.connect(self._set_audio_level)
        self.input_level_changed.connect(self._set_input_level)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    # -- state ---------------------------------------------------------------

    @property
    def state(self) -> str:
        if time.monotonic() - self._last_speech_at < self._SPEECH_HOLD:
            return "speaking"
        return self._base_state

    def set_state(self, state: str) -> None:
        if state not in self.STATES or state == "speaking":
            raise ValueError(f"unknown base voice state: {state}")
        if state != self._base_state:
            self._base_state = state
            if state != "listening":
                self._input_level = 0.0
            self.update()

    def set_model_label(self, text: str) -> None:
        self._model_label = text.strip()
        self.update()

    def set_audio_level(self, level: float) -> None:
        """Thread-safe entry point for the TTS analyser."""
        self.audio_level_changed.emit(level)

    def set_input_level(self, level: float) -> None:
        """Thread-safe entry point for the microphone."""
        self.input_level_changed.emit(level)

    def _set_audio_level(self, level: float) -> None:
        self._audio_level = level
        if level > 0.01:
            self._last_speech_at = time.monotonic()
        elif level == 0.0:
            # Playback reports an exact zero when it ends or is stopped.
            self._last_speech_at = 0.0

    def _set_input_level(self, level: float) -> None:
        if self._base_state == "listening":
            self._input_level = level

    def _tick(self) -> None:
        self._clock = time.monotonic() - self._started
        state = self.state
        target = {"speaking": self._audio_level, "listening": self._input_level}.get(state, 0.0)
        self._level += (target - self._level) * 0.35
        self.update()

    # -- painting ------------------------------------------------------------

    @staticmethod
    def _color(value: str, alpha: int | None = None) -> QColor:
        color = QColor(value)
        if alpha is not None:
            color.setAlpha(max(0, min(255, alpha)))
        return color

    def _state_color(self, state: str) -> str:
        colors = self.palette_colors
        return {"listening": colors.listening, "thinking": colors.thinking}.get(state, colors.accent)

    def paintEvent(self, event) -> None:
        colors = self.palette_colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._color(colors.background))
        chip_space = 40
        radius = max(40.0, min(self.width(), self.height() - chip_space) / 2 - 10)
        # Ring and chips stay together as one block, sitting just above the
        # voice controls; spare height becomes headroom under the dock title.
        top = max(0.0, self.height() - (radius + 10) * 2 - chip_space - 6)
        center = QPointF(self.width() / 2, top + radius + 10)
        self._chip_top = center.y() + radius + 16
        state = self.state
        tone = self._state_color(state)
        t = self._clock

        self._paint_ticks(painter, center, radius, tone, state, t)
        self._paint_outer_arcs(painter, center, radius - 13, tone, t, 200 if state == "idle" else 235)
        main_radius = radius - 25
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._color(colors.structure), 1.4))
        painter.drawEllipse(center, main_radius, main_radius)
        if state == "thinking":
            self._paint_thinking_arc(painter, center, main_radius, t)
        elif state == "speaking":
            self._paint_speaking_arc(painter, center, main_radius, t)
        elif state == "listening":
            breath = (math.sin(t * 3.2) + 1) / 2
            painter.setPen(QPen(self._color(colors.listening, int(70 + 90 * breath + 90 * self._level)), 2.2))
            painter.drawEllipse(center, main_radius, main_radius)

        self._paint_dotted_ring(painter, center, radius * 0.68, t)
        self._paint_ring_waveform(painter, center, radius * 0.52, radius * 0.1, state, t)
        self._paint_core(painter, center, radius * 0.42, tone, state)
        self._paint_chips(painter, state, t)
        painter.end()

    def _paint_ticks(self, painter: QPainter, center: QPointF, radius: float, tone: str, state: str, t: float) -> None:
        structure = self._color(self.palette_colors.structure)
        lit = self._color(tone, 170)
        count = 90
        # A quiet highlight sweeps the scale; faster while thinking.
        sweep_head = (t * (0.35 if state == "thinking" else 0.05)) % 1.0
        for index in range(count):
            angle = 2 * math.pi * index / count - math.pi / 2
            major = index % 5 == 0
            inner = radius - (7.0 if major else 3.5)
            lit_now = (sweep_head - index / count) % 1.0 < 0.08
            painter.setPen(QPen(lit if lit_now else structure, 1.4 if major else 1.0))
            cos, sin = math.cos(angle), math.sin(angle)
            painter.drawLine(
                QPointF(center.x() + cos * inner, center.y() + sin * inner),
                QPointF(center.x() + cos * radius, center.y() + sin * radius),
            )

    @staticmethod
    def _arc(painter: QPainter, center: QPointF, radius: float, start: float, span: float) -> None:
        """Draw an arc in degrees, measured clockwise from twelve o'clock."""
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        painter.drawArc(rect, int((90 - start) * 16), int(-span * 16))

    def _paint_outer_arcs(
        self, painter: QPainter, center: QPointF, radius: float, tone: str, t: float, alpha: int
    ) -> None:
        pen = QPen(self._color(tone, alpha), 3.0)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        drift = t * 4.0
        for start, span in ((-62, 44), (-8, 26), (148, 58), (222, 20), (262, 34)):
            self._arc(painter, center, radius, start + drift, span)

    def _paint_thinking_arc(self, painter: QPainter, center: QPointF, radius: float, t: float) -> None:
        thinking = self.palette_colors.thinking
        head = (t * 250.0) % 360
        segments = 18
        span = 110.0
        for index in range(segments):
            # Fade from the bright head into a transparent tail.
            strength = (index + 1) / segments
            pen = QPen(self._color(thinking, int(235 * strength ** 1.6)), 4.0)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            self._arc(painter, center, radius, head - span + span * index / segments, span / segments + 0.6)
        # A dimmer counter-rotating arc on the inside gives the spin depth.
        painter.setPen(QPen(self._color(thinking, 90), 1.6))
        self._arc(painter, center, radius - 7, -t * 140.0, 70)

    def _paint_speaking_arc(self, painter: QPainter, center: QPointF, radius: float, t: float) -> None:
        speaking = self.palette_colors.speaking
        span = 36 + 70 * min(1.0, self._level * 1.4)
        start = 90 - span / 2
        pen = QPen(self._color(speaking, 235), 4.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        self._arc(painter, center, radius, start, span)
        painter.setPen(QPen(self._color(speaking, 110), 1.4))
        self._arc(painter, center, radius - 7, start + 6, span - 12)
        # Three small blips run along the arc while speech plays.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color(speaking, 230))
        for offset in (0.0, 0.33, 0.66):
            phase = (t * 0.9 + offset) % 1.0
            angle = math.radians(start + span * phase - 90)
            point = QPointF(center.x() + math.cos(angle) * (radius + 7), center.y() + math.sin(angle) * (radius + 7))
            painter.drawEllipse(point, 1.8, 1.8)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_dotted_ring(self, painter: QPainter, center: QPointF, radius: float, t: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color(self.palette_colors.muted, 150))
        count = 56
        rotation = -t * 0.08
        for index in range(count):
            angle = 2 * math.pi * index / count + rotation
            painter.drawEllipse(
                QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius), 1.1, 1.1
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_ring_waveform(
        self, painter: QPainter, center: QPointF, radius: float, amplitude: float, state: str, t: float
    ) -> None:
        """The original soundwave, wrapped around the core instead of drawn across it."""
        phase = t * 4.8
        level = max(0.05 + 0.02 * math.sin(t * 1.6), self._level)
        samples = 160
        outer, inner = [], []
        for index in range(samples + 1):
            theta = 2 * math.pi * index / samples
            # Integer frequencies keep the wave seamless where it meets itself.
            texture = (
                0.48 * math.sin(9 * theta + phase)
                + 0.28 * math.sin(17 * theta - phase * 1.7)
                + 0.14 * math.sin(31 * theta + phase * 0.6)
            )
            offset = abs(texture) * min(1.0, level) * amplitude * 1.6
            cos, sin = math.cos(theta - math.pi / 2), math.sin(theta - math.pi / 2)
            outer.append(QPointF(center.x() + cos * (radius + offset), center.y() + sin * (radius + offset)))
            inner.append(QPointF(center.x() + cos * (radius - offset * 0.6), center.y() + sin * (radius - offset * 0.6)))
        wave_tone = self.palette_colors.listening if state == "listening" else self.palette_colors.accent
        strength = 160 if state == "idle" else 190
        painter.setPen(QPen(self._color(wave_tone, int(strength + level * 85)), 1.8))
        painter.drawPolyline(outer)
        painter.setPen(QPen(self._color(wave_tone, 120), 1.0))
        painter.drawPolyline(inner)

    def _paint_core(self, painter: QPainter, center: QPointF, radius: float, tone: str, state: str) -> None:
        colors = self.palette_colors
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, self._color(tone, 32 if state == "idle" else 60))
        gradient.setColorAt(1.0, self._color(colors.background))
        painter.setBrush(gradient)
        painter.setPen(QPen(self._color(tone, 170 if state == "idle" else 210), 1.4))
        painter.drawEllipse(center, radius, radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        font = QFont("Consolas")
        font.setBold(True)
        font.setPixelSize(max(10, int(radius * 0.3)))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, max(2.0, radius * 0.07))
        painter.setFont(font)
        label_rect = QRectF(center.x() - radius, center.y() - radius * 0.4, radius * 2, radius * 0.6)
        # A soft halo in the state colour, then crisp text on top.
        painter.setPen(self._color(tone, 80))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(label_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, "ARQEN")
        painter.setPen(self._color(colors.text))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "ARQEN")

        small = QFont("Consolas")
        small.setPixelSize(max(7, int(radius * 0.14)))
        small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        painter.setFont(small)
        painter.setPen(self._color(colors.speaking if state == "speaking" else tone, 200))
        painter.drawText(
            QRectF(center.x() - radius, center.y() + radius * 0.22, radius * 2, radius * 0.3),
            Qt.AlignmentFlag.AlignCenter,
            tr(self._LABELS[state]),
        )

    def _paint_chips(self, painter: QPainter, state: str, t: float) -> None:
        colors = self.palette_colors
        font = QFont("Consolas")
        font.setPixelSize(11)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        gap = 8
        labels = [tr("ONLINE")]
        if self._model_label:
            # Provider prefixes ("anthropic/...") add nothing in a chip this small.
            model = self._model_label.rsplit("/", 1)[-1].upper()
            room = self.width() - 24 - (metrics.horizontalAdvance("ONLINE") + 34) - gap - 34
            if room > 40:
                labels.append(metrics.elidedText(model, Qt.TextElideMode.ElideRight, room))
        widths = [metrics.horizontalAdvance(text) + 34 for text in labels]
        x = (self.width() - sum(widths) - gap * (len(widths) - 1)) / 2
        y = getattr(self, "_chip_top", self.height() - 34)
        for index, (text, width) in enumerate(zip(labels, widths)):
            rect = QRectF(x, y, width, 24)
            painter.setBrush(self._color(colors.structure, 90))
            painter.setPen(QPen(self._color(colors.structure), 1.0))
            painter.drawRoundedRect(rect, 12, 12)
            dot = QPointF(rect.left() + 13, rect.center().y())
            painter.setPen(Qt.PenStyle.NoPen)
            if index == 0:
                if state == "speaking":
                    # The green indicator: lit and softly pulsing while Arqen talks.
                    glow = (math.sin(t * 9) + 1) / 2
                    painter.setBrush(self._color(colors.speaking_indicator, int(60 + 80 * glow)))
                    painter.drawEllipse(dot, 5.5, 5.5)
                    painter.setBrush(self._color(colors.speaking_indicator))
                else:
                    painter.setBrush(self._color(colors.accent, 120))
                painter.drawEllipse(dot, 3.2, 3.2)
                painter.setPen(self._color(colors.text if state == "speaking" else colors.muted))
            else:
                painter.setBrush(self._color(colors.accent, 200))
                painter.drawPolygon(QPolygonF([
                    QPointF(dot.x(), dot.y() - 3.5), QPointF(dot.x() + 3.5, dot.y()),
                    QPointF(dot.x(), dot.y() + 3.5), QPointF(dot.x() - 3.5, dot.y()),
                ]))
                painter.setPen(self._color(colors.muted))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(rect.adjusted(24, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            x += width + gap

    def sizeHint(self) -> QSize:
        return QSize(280, 310)

    def minimumSizeHint(self) -> QSize:
        return QSize(220, 250)


_EMPHASIS = re.compile(r"\*\*(?P<strong>[^*\n]+?)\*\*|\*(?P<em>[^*\s][^*\n]*?)\*")


def strip_emphasis(text: str) -> str:
    """Drop markdown emphasis markers without touching arithmetic.

    Streamed text is inserted as plain text, so ``**like this**`` would show
    its asterisks.  Removing every asterisk instead turned ``c * r`` into
    ``c r`` and quietly corrupted any code the model wrote, so only matched
    pairs that sit flush against their content are removed.
    """
    return _EMPHASIS.sub(lambda match: match.group("strong") or match.group("em"), text.replace("\\*", "*"))


def clean_result_markup(text: str) -> str:
    """Normalize escaped Markdown/HTML commonly returned by research agents."""
    cleaned = html.unescape(text or "")
    return re.sub(r"\\([\\`*_#>\[\]()~+-])", r"\1", cleaned)


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


class UsageSplitBar(QWidget):
    """A thin bar split between prompt (input) and completion (output) tokens."""

    def __init__(self, palette: VoicePalette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._input = 0
        self._output = 0
        self.setFixedHeight(6)

    def set_split(self, prompt_tokens: int, completion_tokens: int) -> None:
        self._input, self._output = max(0, prompt_tokens), max(0, completion_tokens)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(QColor(self._palette.structure))
        painter.drawRoundedRect(rect, 3, 3)
        total = self._input + self._output
        if total:
            # Output is what the model wrote, so it gets the accent; a sliver
            # stays visible even when input dwarfs it.
            share = max(0.02, self._output / total) if self._output else 0.0
            width = rect.width() * share
            painter.setBrush(QColor(self._palette.accent))
            painter.drawRoundedRect(QRectF(rect.right() - width, rect.top(), width, rect.height()), 3, 3)
        painter.end()


class StatsPanelWidget(QWidget):
    """Tokens and cost: this chat first, the latest response next, the running total last."""

    def __init__(self, palette: VoicePalette | None = None) -> None:
        super().__init__()
        self._palette = palette or VoicePalette()
        colors = self._palette
        self.setObjectName("statsPanel")
        # One surface with the voice panel; also stops the app-wide QWidget
        # background from painting dark bars behind every label.  A plain
        # QWidget ignores its stylesheet background without this attribute.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget {{ background: {colors.background}; color: {colors.text}; font-family: Consolas, monospace; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 14)
        layout.setSpacing(4)

        layout.addWidget(self._heading(tr("THIS CHAT")))
        self.session_cost = self._label("—", size=24, color=colors.text, bold=True)
        layout.addWidget(self.session_cost)
        self.session_tokens = self._label("—", size=11, color=colors.muted)
        layout.addWidget(self.session_tokens)
        layout.addSpacing(8)
        self.split_bar = UsageSplitBar(colors)
        layout.addWidget(self.split_bar)
        split_row = QHBoxLayout()
        self.split_in = self._label("—", size=10, color=colors.muted)
        self.split_out = self._label("—", size=10, color=colors.accent)
        self.split_out.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        split_row.addWidget(self.split_in)
        split_row.addStretch(1)
        split_row.addWidget(self.split_out)
        layout.addLayout(split_row)

        layout.addSpacing(12)
        layout.addWidget(self._heading(tr("LATEST RESPONSE")))
        tiles = QHBoxLayout()
        tiles.setSpacing(6)
        self.last_values: dict[str, QLabel] = {}
        for key, caption in (("time", "time"), ("tokens", "tokens"), ("cost", "cost")):
            tile = QFrame()
            tile.setObjectName("statTile")
            tile.setStyleSheet(
                f"QFrame#statTile {{ border: 1px solid {colors.structure}; border-radius: 6px; }}"
            )
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(8, 6, 8, 6)
            tile_layout.setSpacing(0)
            value = self._label("—", size=12, color=colors.text, bold=True)
            tile_layout.addWidget(value)
            tile_layout.addWidget(self._label(tr(caption), size=9, color=colors.muted))
            tiles.addWidget(tile, 1)
            self.last_values[key] = value
        layout.addLayout(tiles)

        layout.addSpacing(14)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {colors.structure};")
        layout.addWidget(divider)
        layout.addSpacing(4)
        footer = QHBoxLayout()
        footer.addWidget(self._heading(tr("TOTAL")))
        footer.addStretch(1)
        self.total_line = self._label("—", size=10, color=colors.muted)
        footer.addWidget(self.total_line)
        layout.addLayout(footer)
        layout.addStretch(1)
        self.update_usage(None, None, None, None)

    def _label(self, text: str, *, size: int, color: str, bold: bool = False) -> QLabel:
        label = QLabel(text)
        weight = "font-weight: bold;" if bold else ""
        label.setStyleSheet(f"color: {color}; font-size: {size}px; {weight}")
        return label

    def _heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {self._palette.accent}; font-size: 10px; letter-spacing: 2px;")
        return label

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
            for label in (self.session_cost, self.session_tokens, self.split_in, self.split_out, self.total_line):
                label.setText("—")
            for value in self.last_values.values():
                value.setText("—")
            self.split_bar.set_split(0, 0)
            return
        self.session_cost.setText(self._money(session.cost))
        self.session_tokens.setText(f"{self._count(session.total_tokens)} {tr('tokens')}")
        self.split_bar.set_split(session.prompt_tokens, session.completion_tokens)
        self.split_in.setText(f"{tr('in')} {self._count(session.prompt_tokens)}")
        self.split_out.setText(f"{tr('out')} {self._count(session.completion_tokens)}")
        self.total_line.setText(f"{self._count(total.total_tokens)} {tr('tokens')}  ·  {self._money(total.cost)}")
        if turn is not None:
            self.last_values["tokens"].setText(self._count(turn.total_tokens))
            self.last_values["cost"].setText(self._money(turn.cost))
        self.last_values["time"].setText("—" if elapsed_ms is None else f"{elapsed_ms / 1000:.1f} s")


class _SectionHeader(QFrame):
    """A header row that toggles the section below it."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ArqenWindow(QMainWindow):
    microphone_status = pyqtSignal(str)
    microphone_result = pyqtSignal(str)

    def __init__(self, engine: ConversationEngine, provider_label: str = "unknown", profile_name: str = "") -> None:
        super().__init__()
        self.engine = engine
        self.engine.on_tool_request = self.show_tool_request
        self.setWindowTitle("Arqen")
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
        navigation_layout.addWidget(QLabel(tr("MISSION CONTROL")))
        navigation_layout.addWidget(QLabel(tr("OVERVIEW"), objectName="navSection"))
        for label, icon in (("Dashboard", "⌂"), ("Chat", "◌"), ("Mission Control", "◈")):
            self._add_navigation_button(navigation_layout, label, icon)
        navigation_layout.addWidget(QLabel(tr("SYSTEM"), objectName="navSection"))
        for label, icon in (("Agents", "♙"), ("Activity", "≋"), ("Memory", "▤"), ("Tools", "⚿"), ("Connections", "⧉")):
            self._add_navigation_button(navigation_layout, label, icon)
        navigation_layout.addWidget(QLabel(tr("OPERATIONS"), objectName="navSection"))
        for label, icon in (("Tasks", "✓"), ("Workflows", "⌘"), ("Schedules", "◷"), ("Content", "◇")):
            self._add_navigation_button(navigation_layout, label, icon)
        navigation_layout.addStretch(1)
        settings_nav = QPushButton(f"⚙  {tr('Settings')}")
        settings_nav.setObjectName("navButton")
        settings_nav.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_nav.clicked.connect(lambda: (self._select_navigation("Settings"), self.open_settings()))
        navigation_layout.addWidget(settings_nav)
        self.navigation_buttons["Settings"] = settings_nav
        layout.addWidget(navigation)
        # Created here, shown in the voice panel (see _create_visualization_dock).
        self.mic_button = QPushButton("🎙")
        self.mic_button.setAccessibleName(tr("Start/stop microphone recording"))
        self.mic_button.clicked.connect(self.toggle_microphone)
        self.voice_button = QPushButton("🔇")
        self.voice_button.setAccessibleName(tr("Toggle voice mode"))
        self.voice_button.clicked.connect(self.toggle_voice_mode)

        content = QWidget()
        chat_page_layout = QHBoxLayout(content)
        chat_page_layout.setContentsMargins(0, 0, 0, 0)
        chat_page_layout.setSpacing(10)
        chat_page_layout.addWidget(self._build_chat_list())
        conversation = QWidget()
        content_layout = QVBoxLayout(conversation)
        content_layout.setContentsMargins(0, 0, 0, 0)
        chat_page_layout.addWidget(conversation, 1)
        header = QFrame(objectName="panel")
        header_layout = QVBoxLayout(header)
        header_layout.addWidget(QLabel("ARQEN", objectName="title"))
        self.provider_label = provider_label
        self.profile_name = profile_name
        self.status = QLabel(
            self.provider_status(tr("READY")),
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
        placeholder_label = QLabel(tr("Conversation will appear here..."), chat_surface)
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        placeholder_label.setStyleSheet("color: #f2f0eb; background: transparent; padding-top: 8px;")
        placeholder_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        chat_surface_layout.addWidget(placeholder_label, 0, 0)
        self.output.textChanged.connect(lambda: placeholder_label.setVisible(not bool(self.output.toPlainText())))
        input_row = QHBoxLayout()
        self.input = ChatInput()
        self.input.setPlaceholderText(tr("Type a message... (Shift+Enter for a new line)"))
        # Matches the single-line field it replaced, which took its look from the theme.
        self.input.setStyleSheet(
            f"QPlainTextEdit#chatInput {{ background: {CyberpunkGreenTheme.panel_alt}; "
            f"border: 1px solid {CyberpunkGreenTheme.border}; border-radius: 6px; padding: 5px 4px; "
            f"color: {CyberpunkGreenTheme.text}; }}"
        )
        self.microphone_status.connect(lambda text: self.set_status(tr_status(text)))
        self.microphone_status.connect(self._on_microphone_status)
        self.microphone_result.connect(self._handle_microphone_result)
        self.microphone = MicrophoneRecorder(
            on_result=self.microphone_result.emit,
            on_status=self.microphone_status.emit,
        )
        self.input.returnPressed.connect(self.send_message)
        send = QPushButton("▶")
        send.setToolTip(tr("Send"))
        send.setAccessibleName(tr("Send"))
        send.setStyleSheet("QPushButton { background: transparent; color: #b7ff18; border: none; font-size: 32px; font-weight: 700; padding: 5px 8px 0 8px; } QPushButton:hover { color: #e1ff8a; }")
        send.clicked.connect(self.send_message)
        self.stop_button = QPushButton("■")
        self.stop_button.setToolTip(tr("Stop"))
        self.stop_button.setAccessibleName(tr("Stop"))
        self.stop_button.setStyleSheet("QPushButton { background: transparent; color: #b7ff18; border: none; font-size: 28px; font-weight: 700; padding: 0 8px; } QPushButton:hover { color: #e1ff8a; }")
        self.stop_button.clicked.connect(self.stop_response)
        self.stop_button.setEnabled(False)
        self.confirm_button = QPushButton(tr("CONFIRM"))
        self.cancel_button = QPushButton(tr("CANCEL"))
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
        self.navigation_stack = QStackedWidget()
        dashboard = QWidget()
        dashboard_layout = QVBoxLayout(dashboard)
        dashboard_layout.setContentsMargins(18, 18, 18, 18)
        dashboard_layout.setSpacing(12)
        dashboard_layout.addWidget(QLabel(tr("DASHBOARD"), objectName="title"))
        dashboard_layout.addWidget(QLabel(tr("Mission Control // system overview"), objectName="status"))
        cards = QGridLayout()
        cards.setSpacing(10)
        self.dashboard_cards: dict[str, QLabel] = {}
        for index, (key, label) in enumerate((("agents", "AGENTS"), ("tasks", "ACTIVE TASKS"), ("approvals", "APPROVALS"), ("workflows", "WORKFLOW RUNS"))):
            card = QFrame(objectName="panel")
            card.setMinimumHeight(92)
            card.setStyleSheet(
                "QFrame#panel { background: #171d21; border: 1px solid #30383a; border-radius: 8px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.addWidget(QLabel(tr(label)))
            value = QLabel("0", objectName="title")
            value.setStyleSheet("color: #c7ff2f; font-size: 26px; font-weight: 700;")
            card_layout.addWidget(value)
            self.dashboard_cards[key] = value
            cards.addWidget(card, index // 2, index % 2)
        dashboard_layout.addLayout(cards)
        dashboard_layout.addWidget(QLabel(tr("LATEST ACTIVITY"), objectName="sectionLabel"))
        self.dashboard_activity = QListWidget()
        self.dashboard_activity.setSpacing(4)
        self.dashboard_activity.setStyleSheet(
            "QListWidget { background: #171d21; border: 1px solid #30383a; border-radius: 8px; padding: 6px; }"
            "QListWidget::item { padding: 7px; border-bottom: 1px solid #252d30; color: #c4cec9; }"
            "QListWidget::item:last { border-bottom: none; }"
        )
        dashboard_layout.addWidget(self.dashboard_activity, 1)
        open_chat = QPushButton(tr("OPEN ARQEN CHAT"))
        self._style_page_action(open_chat, primary=True)
        open_chat.clicked.connect(lambda: self._select_navigation("Chat"))
        dashboard_layout.addWidget(open_chat)
        self.navigation_stack.addWidget(dashboard)
        self.navigation_stack.addWidget(content)
        for label in ("Tasks", "Workflows", "Schedules", "Agents", "Activity", "Memory", "Tools", "Content", "Connections"):
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
            if label == "Tools":
                self._add_tools_view()
                continue
            if label == "Content":
                self._add_content_view()
                continue
            if label == "Connections":
                self._add_connections_view()
                continue
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(QLabel(tr(label).upper(), objectName="title"))
            page_layout.addWidget(QLabel(tr("This view will be expanded in the next UI step.")))
            page_layout.addStretch(1)
            self.navigation_stack.addWidget(page)
        main_column = QWidget()
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)
        self._chat_confirmation: tuple[str, dict] | None = None
        self.approval_bar = self._build_approval_bar()
        main_layout.addWidget(self.approval_bar)
        main_layout.addWidget(self.navigation_stack, 1)
        layout.addWidget(main_column, 1)
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
        page_layout.addWidget(QLabel(tr("TASKS"), objectName="title"))
        page_layout.addWidget(QLabel(tr("Monitor, run and retry agent work.")))
        self.tasks_attention_only = False
        task_filters = QHBoxLayout()
        all_tasks = QPushButton(tr("ALL TASKS"))
        attention_tasks = QPushButton(tr("NEEDS ATTENTION"))
        for button in (all_tasks, attention_tasks):
            self._style_page_action(button)
            task_filters.addWidget(button)
        task_filters.addStretch(1)
        all_tasks.clicked.connect(lambda: self._set_task_filter(False))
        attention_tasks.clicked.connect(lambda: self._set_task_filter(True))
        page_layout.addLayout(task_filters)
        self.mission_tasks = QListWidget()
        self.mission_tasks.setSpacing(8)
        self.mission_tasks.setWordWrap(True)
        self.mission_tasks.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { background: #171d21; border: 1px solid #30383a; "
            "border-radius: 8px; padding: 12px; margin: 0 2px; color: #f2f0eb; }"
            "QListWidget::item:hover { background: #20282a; border-color: #66736e; }"
            "QListWidget::item:selected { background: #202a20; border: 1px solid #b7ff18; color: #f2f0eb; }"
        )
        self.mission_tasks.itemClicked.connect(self._show_mission_task)
        page_layout.addWidget(self.mission_tasks, 1)
        self.mission_details = QTextEdit(readOnly=True)
        self.mission_details.setPlaceholderText(tr("Select a task to view its summary and event history."))
        self.mission_details.setMinimumHeight(170)
        self.mission_details.setStyleSheet(
            "QTextEdit { background: #111516; border: 1px solid #30383a; border-radius: 8px; "
            "padding: 12px; color: #c4cec9; selection-background-color: #33452a; }"
        )
        page_layout.addWidget(self.mission_details)
        self.mission_result_button = QPushButton(tr("OPEN FULL RESULT"))
        self._style_page_action(self.mission_result_button)
        self.mission_result_button.setEnabled(False)
        self.mission_result_button.clicked.connect(self._open_selected_task_result)
        page_layout.addWidget(self.mission_result_button, alignment=Qt.AlignmentFlag.AlignLeft)
        page_layout.addWidget(QLabel(tr("PENDING APPROVALS"), objectName="sectionLabel"))
        self.mission_approvals = QListWidget()
        self.mission_approvals.itemClicked.connect(self._show_selected_approval)
        page_layout.addWidget(self.mission_approvals)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW TASK", self._create_mission_task), ("RUN SELECTED TASK", self._run_mission_task), ("RETRY", self._retry_mission_task), ("DELETE TASK", self._delete_queued_task))):
            button = QPushButton(tr(label))
            self._style_page_action(button, primary=index == 0)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        page_layout.addLayout(row)
        approval_row = QHBoxLayout()
        for index, (label, status) in enumerate((("APPROVE", "approved"), ("REJECT", "rejected"))):
            button = QPushButton(tr(label))
            self._style_page_action(button, primary=index == 0)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _, value=status: self._decide_mission_approval(value))
            approval_row.addWidget(button)
        approval_row.addStretch(1)
        page_layout.addLayout(approval_row)
        self.navigation_stack.addWidget(page)

    def _add_workflows_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(4)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        page_layout.addWidget(QLabel(tr("WORKFLOWS"), objectName="title"))
        page_layout.addWidget(QLabel(tr("Build and run multi-agent pipelines."), objectName="status"))
        page_layout.addWidget(QLabel(tr("AVAILABLE WORKFLOWS"), objectName="sectionLabel"))
        self.mission_workflows = QListWidget()
        self.mission_workflows.setSpacing(8)
        self.mission_workflows.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { background: #171d21; border: 1px solid #30383a; "
            "border-radius: 8px; padding: 11px; margin: 0 2px; color: #f2f0eb; }"
            "QListWidget::item:hover { background: #20282a; border-color: #66736e; }"
            "QListWidget::item:selected { background: #202a20; border: 1px solid #b7ff18; }"
        )
        page_layout.addWidget(self.mission_workflows)
        page_layout.addWidget(QLabel(tr("RECENT RUNS"), objectName="sectionLabel"))
        self.mission_workflow_runs = QListWidget()
        self.mission_workflow_runs.setSpacing(6)
        self.mission_workflow_runs.setStyleSheet(
            "QListWidget { background: #111516; border: 1px solid #30383a; border-radius: 8px; padding: 5px; }"
            "QListWidget::item { padding: 8px; border-bottom: 1px solid #252d30; color: #c4cec9; }"
            "QListWidget::item:selected { background: #202a20; color: #f2f0eb; }"
        )
        self.mission_workflow_runs.itemClicked.connect(self._show_workflow_run)
        page_layout.addWidget(self.mission_workflow_runs)
        self.mission_workflow_details = QTextEdit(readOnly=True)
        self.mission_workflow_details.setPlaceholderText(tr("Select a workflow run to view its results."))
        page_layout.addWidget(self.mission_workflow_details)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW WORKFLOW", self._create_mission_workflow), ("RUN WORKFLOW", self._run_mission_workflow), ("RESUME RUN", self._resume_mission_workflow))):
            button = QPushButton(tr(label))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        page_layout.addLayout(row)
        self.navigation_stack.addWidget(page)

    def _show_workflow_run(self, item: QListWidgetItem) -> None:
        run = self.mission_store.get_workflow_run(item.data(Qt.ItemDataRole.UserRole))
        if run is None:
            return
        if not run.results:
            self.mission_workflow_details.setPlainText(tr("Status: {status}\nNo results yet.", status=status_label(run.status)))
            return
        lines = [f"Status: {status_label(run.status)}", tr("Completed steps: {count}", count=run.current_step), ""]
        for index, result in enumerate(run.results, 1):
            lines.extend((tr("STEP {index}", index=index), result, ""))
        self.mission_workflow_details.setPlainText("\n".join(lines).rstrip())

    def _add_schedules_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(10)
        page_layout.addWidget(QLabel(tr("SCHEDULES"), objectName="title"))
        page_layout.addWidget(QLabel(tr("Automate recurring tasks and workflows."), objectName="status"))
        self.mission_schedules = QListWidget()
        self.mission_schedules.setSpacing(8)
        self.mission_schedules.setWordWrap(True)
        self.mission_schedules.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { background: #171d21; border: 1px solid #30383a; "
            "border-radius: 8px; padding: 11px; margin: 0 2px; color: #f2f0eb; }"
            "QListWidget::item:hover { background: #20282a; border-color: #66736e; }"
            "QListWidget::item:selected { background: #202a20; border: 1px solid #b7ff18; }"
        )
        page_layout.addWidget(self.mission_schedules, 1)
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW SCHEDULE", self._create_mission_schedule), ("ENABLE/DISABLE", self._toggle_mission_schedule), ("DELETE SCHEDULE", self._delete_mission_schedule))):
            button = QPushButton(tr(label))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        page_layout.addLayout(row)
        self.navigation_stack.addWidget(page)

    def _add_agents_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(4)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        title = QLabel(tr("AGENTS"), objectName="title")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        status = QLabel(tr("Manage runtimes, tools and approval policies."), objectName="status")
        status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        page_layout.addWidget(title)
        page_layout.addWidget(status)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #30383a; border: none;")
        page_layout.addWidget(divider)
        self.nexus_card_host = QWidget()
        self.nexus_card_layout = QHBoxLayout(self.nexus_card_host)
        self.nexus_card_layout.setContentsMargins(0, 0, 0, 0)
        self.nexus_card_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.nexus_card_host.setFixedHeight(162)
        self.nexus_card_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        page_layout.addWidget(self.nexus_card_host, alignment=Qt.AlignmentFlag.AlignTop)
        self.agent_group_lists: dict[str, QListWidget] = {}
        for group in ("RESEARCH", "PRODUCTION", "DISTRIBUTION & REVIEW"):
            page_layout.addWidget(QLabel(tr(group), objectName="sectionLabel"))
            group_list = QListWidget()
            group_list.setViewMode(QListWidget.ViewMode.IconMode)
            group_list.setResizeMode(QListWidget.ResizeMode.Adjust)
            group_list.setMovement(QListWidget.Movement.Static)
            group_list.setSpacing(10)
            group_list.setGridSize(QSize(280, 170))
            group_list.setUniformItemSizes(True)
            group_list.setWordWrap(True)
            group_list.setStyleSheet(
                "QListWidget { background: transparent; border: none; }"
                "QListWidget::item { background: transparent; border: none; padding: 0; }"
            )
            group_list.itemClicked.connect(lambda _, source=group_list: setattr(self, "mission_agents", source))
            self.agent_group_lists[group] = group_list
            group_list.setFixedHeight(170)
            page_layout.addWidget(group_list)
        self.mission_agents = self.agent_group_lists["RESEARCH"]
        row = QHBoxLayout()
        for index, (label, handler) in enumerate((("NEW AGENT", self._create_mission_agent), ("EDIT", self._edit_mission_agent), ("ENABLE/DISABLE", self._toggle_mission_agent))):
            button = QPushButton(tr(label))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button, primary=index == 0)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        page_layout.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.navigation_stack.addWidget(scroll)

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
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(10)
        page_layout.addWidget(QLabel(tr("ACTIVITY"), objectName="title"))
        page_layout.addWidget(QLabel(tr("Live system events and agent activity."), objectName="status"))
        self.activity_view_list = QListWidget()
        self.activity_view_list.setSpacing(3)
        self.activity_view_list.setStyleSheet(
            "QListWidget { background: #111516; border: 1px solid #30383a; border-radius: 8px; padding: 6px; }"
            "QListWidget::item { padding: 9px 8px; border-bottom: 1px solid #252d30; color: #c4cec9; }"
            "QListWidget::item:hover { background: #20282a; }"
            "QListWidget::item:selected { background: #202a20; border-left: 2px solid #b7ff18; }"
        )
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
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(QLabel(tr("MEMORY"), objectName="title"))
        heading.addStretch(1)
        self.memory_reflect_button = QPushButton(tr("REFLECT"))
        self.memory_reflect_button.setToolTip(tr(
            "Arqen reads recent tasks and chats and suggests lasting lessons. Costs one model call."
        ))
        self.memory_reflect_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._style_page_action(self.memory_reflect_button, primary=True)
        self.memory_reflect_button.clicked.connect(self._start_reflection)
        heading.addWidget(self.memory_reflect_button)
        page_layout.addLayout(heading)
        self.memory_summary = QLabel("", objectName="status")
        page_layout.addWidget(self.memory_summary)
        self.memory_reflect_status = QLabel("")
        self.memory_reflect_status.setWordWrap(True)
        self.memory_reflect_status.setStyleSheet("color: #9fce20; font-size: 11px;")
        self.memory_reflect_status.hide()
        page_layout.addWidget(self.memory_reflect_status)

        self.memory_proposals_heading = QLabel(tr("SUGGESTIONS TO REVIEW"), objectName="sectionLabel")
        page_layout.addWidget(self.memory_proposals_heading)
        self.memory_proposals_host = QWidget()
        self.memory_proposals_layout = QVBoxLayout(self.memory_proposals_host)
        self.memory_proposals_layout.setContentsMargins(0, 0, 0, 0)
        self.memory_proposals_layout.setSpacing(6)
        page_layout.addWidget(self.memory_proposals_host)

        page_layout.addWidget(QLabel(tr("APPROVED MEMORIES"), objectName="sectionLabel"))
        self.memory_view_list = QListWidget()
        self.memory_view_list.setWordWrap(True)
        self.memory_view_list.setSpacing(2)
        self.memory_view_list.setStyleSheet(
            "QListWidget { background: #111516; border: 1px solid #30383a; border-radius: 8px; padding: 6px; }"
            "QListWidget::item { padding: 8px; border-bottom: 1px solid #252d30; }"
            "QListWidget::item:selected { background: #1f2a20; border-left: 2px solid #b7ff18; }"
        )
        self.memory_view_list.itemDoubleClicked.connect(self._edit_memory_item)
        self.memory_view_list.currentItemChanged.connect(lambda *_: self._update_memory_actions())
        page_layout.addWidget(self.memory_view_list, 1)
        actions = QHBoxLayout()
        edit = QPushButton(tr("EDIT"))
        self.memory_obsolete_button = QPushButton(tr("MARK OBSOLETE"))
        delete = QPushButton(tr("DELETE"))
        for button in (edit, self.memory_obsolete_button, delete):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button)
            actions.addWidget(button)
        actions.addStretch(1)
        edit.clicked.connect(lambda: self._edit_memory_item())
        self.memory_obsolete_button.clicked.connect(self._toggle_memory_obsolete)
        delete.clicked.connect(self._delete_memory_item)
        page_layout.addLayout(actions)
        self._refresh_memory_view()
        self.navigation_stack.addWidget(page)

    _TOOL_TABS = ("CATALOG", "AGENTS", "LOG")
    _TOOL_CARD_COLUMNS = 3

    def _add_tools_view(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        layout.addWidget(QLabel(tr("TOOL GATEWAY"), objectName="title"))
        self.tools_summary = QLabel("", objectName="status")
        layout.addWidget(self.tools_summary)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.tools_tab_buttons: list[QPushButton] = []
        for index, name in enumerate(self._TOOL_TABS):
            button = QPushButton(tr(name))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _, value=index: self._select_tools_tab(value))
            controls.addWidget(button)
            self.tools_tab_buttons.append(button)
        controls.addStretch(1)
        self.tools_search = QLineEdit()
        self.tools_search.setPlaceholderText(tr("Search tools..."))
        self.tools_search.setClearButtonEnabled(True)
        self.tools_search.setFixedWidth(260)
        self.tools_search.textChanged.connect(lambda _: self._refresh_tool_catalog())
        controls.addWidget(self.tools_search)
        # A toggle chip rather than a checkbox: the theme draws no checkbox indicator.
        self.tools_approval_only = QPushButton(tr("REQUIRES APPROVAL"))
        self.tools_approval_only.setCheckable(True)
        self.tools_approval_only.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools_approval_only.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.tools_approval_only.setStyleSheet(
            "QPushButton { background: #171d21; color: #c4cec9; border: 1px solid #30383a; border-radius: 5px; padding: 9px 14px; }"
            "QPushButton:hover { color: #f2f0eb; border-color: #66736e; }"
            "QPushButton:checked { color: #ffd166; border-color: #ffd166; background: #221f14; }"
        )
        self.tools_approval_only.toggled.connect(lambda _: self._refresh_tool_catalog())
        controls.addWidget(self.tools_approval_only)
        self.tools_expand_all = QPushButton(tr("SHOW ALL"))
        self.tools_expand_all.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._style_page_action(self.tools_expand_all)
        self.tools_expand_all.clicked.connect(self._toggle_all_tool_sections)
        controls.addWidget(self.tools_expand_all)
        layout.addLayout(controls)
        # Which catalogue sections are open; kept between sessions.
        stored = QSettings("Arqen", "Arqen Desktop").value("tools_open_sections", [])
        self._tool_sections_open: set[str] = set(stored if isinstance(stored, list) else [stored] if stored else [])
        # Sections closed by hand while a search or filter shows everything that matches.
        self._tool_sections_hidden: set[str] = set()
        self._tool_filter_seen = ("", False)

        self.tools_stack = QStackedWidget()
        self.tools_catalog_host, self.tools_catalog_layout = self._scrolling_page(self.tools_stack)
        self.tools_agents_host, self.tools_agents_layout = self._scrolling_page(self.tools_stack)
        self.tools_log = QListWidget()
        self.tools_log.setSpacing(2)
        # No item colour here: it would override the per-status colours.
        self.tools_log.setStyleSheet(
            "QListWidget { background: #111516; border: 1px solid #30383a; border-radius: 8px; padding: 6px; }"
            "QListWidget::item { padding: 8px; border-bottom: 1px solid #252d30; }"
        )
        self.tools_stack.addWidget(self.tools_log)
        layout.addWidget(self.tools_stack, 1)
        self._select_tools_tab(0)
        self.navigation_stack.addWidget(page)

    @staticmethod
    def _scrolling_page(stack: QStackedWidget) -> tuple[QWidget, QVBoxLayout]:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 6, 0)
        host_layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        stack.addWidget(scroll)
        return host, host_layout

    def _select_tools_tab(self, index: int) -> None:
        self.tools_stack.setCurrentIndex(index)
        for position, button in enumerate(self.tools_tab_buttons):
            self._style_page_action(button, primary=position == index)
        # Search and filter only apply to the catalogue.
        self.tools_search.setVisible(index == 0)
        self.tools_approval_only.setVisible(index == 0)
        self.tools_expand_all.setVisible(index == 0)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
            elif child.layout() is not None:
                ArqenWindow._clear_layout(child.layout())

    def _tool_users(self) -> dict[str, list[str]]:
        """Agent names per tool, from the Mission Control agents' allowlists."""
        users: dict[str, list[str]] = {}
        store = getattr(self, "mission_store", None)
        if store is None:
            return users
        agents = store.list_agents()
        self._tool_agent_total = len(agents)
        for agent in sorted(agents, key=lambda entry: entry.name.lower()):
            for tool in agent.allowed_tools:
                users.setdefault(tool, []).append(agent.name)
        return users

    def _refresh_tools_view(self) -> None:
        if not hasattr(self, "tools_stack"):
            return
        catalog = self.engine.gateway.catalog()
        approvals = sum(1 for item in catalog if item["requires_confirmation"])
        self.tools_summary.setText(
            tr("{count} tools  ·  {approval} require approval", count=len(catalog), approval=approvals)
        )
        self._refresh_tool_catalog()
        self._refresh_tool_agents()
        self._refresh_tool_log()

    def _refresh_tool_catalog(self) -> None:
        if not hasattr(self, "tools_catalog_layout"):
            return
        self._clear_layout(self.tools_catalog_layout)
        query = self.tools_search.text().casefold().strip()
        approval_only = self.tools_approval_only.isChecked()
        filtering = bool(query) or approval_only
        if (query, approval_only) != self._tool_filter_seen:
            # A new search opens every section it matches again.
            self._tool_filter_seen = (query, approval_only)
            self._tool_sections_hidden.clear()
        users = self._tool_users()
        sections: dict[str, list[tuple[dict, ToolInfo]]] = {}
        for item in self.engine.gateway.catalog():
            info = tool_info(item["name"], item["description"])
            if approval_only and not item["requires_confirmation"]:
                continue
            haystack = " ".join((item["name"], info.title, info.summary, info.category)).casefold()
            if query and query not in haystack:
                continue
            sections.setdefault(info.category, []).append((item, info))
        if not sections:
            empty = QLabel(tr("No tools match the search."))
            empty.setStyleSheet("color: #8d969d; padding: 12px 2px;")
            self.tools_catalog_layout.addWidget(empty)
        shown = [category for category in CATEGORIES if sections.get(category)]
        self._tool_sections_shown = shown
        for category in shown:
            entries = sections[category]
            if filtering:
                expanded = category not in self._tool_sections_hidden
            else:
                expanded = category in self._tool_sections_open
            section_users = sorted({name for item, _ in entries for name in users.get(item["name"], [])}, key=str.lower)
            self.tools_catalog_layout.addWidget(self._tool_section_header(category, entries, section_users, expanded))
            if not expanded:
                continue
            grid = QGridLayout()
            grid.setSpacing(8)
            for index, (item, info) in enumerate(entries):
                card = self._tool_card(item, info, users.get(item["name"], []))
                grid.addWidget(card, index // self._TOOL_CARD_COLUMNS, index % self._TOOL_CARD_COLUMNS)
            for column in range(self._TOOL_CARD_COLUMNS):
                grid.setColumnStretch(column, 1)
            self.tools_catalog_layout.addLayout(grid)
            self.tools_catalog_layout.addSpacing(8)
        self.tools_catalog_layout.addStretch(1)
        self.tools_expand_all.setText(tr("HIDE ALL") if shown and self._all_tool_sections_open() else tr("SHOW ALL"))

    def _all_tool_sections_open(self) -> bool:
        shown = getattr(self, "_tool_sections_shown", [])
        if self.tools_search.text().strip() or self.tools_approval_only.isChecked():
            return not (set(shown) & self._tool_sections_hidden)
        return set(shown) <= self._tool_sections_open

    def _tool_section_header(self, category: str, entries: list, section_users: list[str], expanded: bool) -> QFrame:
        header = _SectionHeader(objectName="toolSection")
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        border = "#b7ff18" if expanded else "#30383a"
        header.setStyleSheet(
            f"QFrame#toolSection {{ background: #13181b; border: 1px solid {border}; border-radius: 8px; }}"
            "QFrame#toolSection:hover { border-color: #9fce20; }"
        )
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        arrow = QLabel("▾" if expanded else "▸")
        arrow.setFixedWidth(14)
        arrow.setStyleSheet("color: #b7ff18; font-size: 14px; border: none;")
        row.addWidget(arrow)
        name = QLabel(category.upper())
        name.setStyleSheet("color: #f2f0eb; font-weight: bold; font-size: 13px; letter-spacing: 1px; border: none;")
        row.addWidget(name)
        count = QLabel(tr("{count} tools", count=len(entries)))
        count.setStyleSheet("color: #8d969d; font-size: 11px; border: none;")
        row.addWidget(count)
        approvals = sum(1 for item, _ in entries if item["requires_confirmation"])
        if approvals:
            badge = QLabel(tr("{count} require approval", count=approvals))
            badge.setStyleSheet("color: #ffd166; border: 1px solid #6b5a2a; border-radius: 8px; padding: 1px 7px; font-size: 10px;")
            row.addWidget(badge)
        row.addStretch(1)
        everyone = len(section_users) > 1 and len(section_users) == getattr(self, "_tool_agent_total", 0)
        if section_users:
            text = tr("Used by: {agents}", agents=tr("all agents") if everyone else " · ".join(section_users))
            color = "#9fce20"
        else:
            text, color = tr("No agent uses these"), "#657078"
        used_by = QLabel(text)
        used_by.setStyleSheet(f"color: {color}; font-size: 11px; border: none;")
        row.addWidget(used_by)
        header.clicked.connect(lambda name=category: self._toggle_tool_section(name))
        return header

    def _toggle_tool_section(self, category: str) -> None:
        if self.tools_search.text().strip() or self.tools_approval_only.isChecked():
            self._tool_sections_hidden ^= {category}
        else:
            self._tool_sections_open ^= {category}
            self._save_tool_sections()
        self._refresh_tool_catalog()

    def _toggle_all_tool_sections(self) -> None:
        shown = set(getattr(self, "_tool_sections_shown", []))
        filtering = self.tools_search.text().strip() or self.tools_approval_only.isChecked()
        opening = not self._all_tool_sections_open()
        if filtering:
            self._tool_sections_hidden = set() if opening else set(shown)
        else:
            self._tool_sections_open = (self._tool_sections_open | shown) if opening else (self._tool_sections_open - shown)
            self._save_tool_sections()
        self._refresh_tool_catalog()

    def _save_tool_sections(self) -> None:
        QSettings("Arqen", "Arqen Desktop").setValue("tools_open_sections", sorted(self._tool_sections_open))

    def _tool_card(self, item: dict, info: ToolInfo, agents: list[str]) -> QFrame:
        card = QFrame(objectName="toolCard")
        needs_approval = item["requires_confirmation"]
        border = "#6b5a2a" if needs_approval else "#30383a"
        card.setStyleSheet(
            f"QFrame#toolCard {{ background: #171d21; border: 1px solid {border}; border-radius: 8px; }}"
        )
        card.setToolTip(item["description"])
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(3)
        heading = QHBoxLayout()
        title = QLabel(info.title)
        title.setStyleSheet("color: #f2f0eb; font-weight: bold; font-size: 13px;")
        heading.addWidget(title)
        heading.addStretch(1)
        if needs_approval:
            badge = QLabel(tr("APPROVAL"))
            badge.setStyleSheet(
                "color: #ffd166; border: 1px solid #ffd166; border-radius: 8px; padding: 1px 6px; font-size: 9px;"
            )
            heading.addWidget(badge)
        card_layout.addLayout(heading)
        name = QLabel(item["name"])
        name.setStyleSheet("color: #657078; font-size: 10px;")
        card_layout.addWidget(name)
        summary = QLabel(info.summary)
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #c4cec9; font-size: 11px;")
        card_layout.addWidget(summary)
        if agents:
            # A tool every agent has is baseline; listing all eight names is noise.
            everyone = len(agents) > 1 and len(agents) == getattr(self, "_tool_agent_total", 0)
            names = tr("all agents") if everyone else " · ".join(agents)
            used_by = QLabel(tr("Used by: {agents}", agents=names))
            used_by.setWordWrap(True)
            used_by.setStyleSheet("color: #9fce20; font-size: 10px; padding-top: 2px;")
            card_layout.addWidget(used_by)
        card_layout.addStretch(1)
        return card

    def _refresh_tool_agents(self) -> None:
        self._clear_layout(self.tools_agents_layout)
        store = getattr(self, "mission_store", None)
        agents = sorted(store.list_agents(), key=lambda entry: entry.name.lower()) if store is not None else []
        for agent in agents:
            card = QFrame(objectName="toolCard")
            card.setStyleSheet("QFrame#toolCard { background: #171d21; border: 1px solid #30383a; border-radius: 8px; }")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(3)
            heading = QHBoxLayout()
            heading.setSpacing(10)
            name = QLabel(agent.name)
            name.setStyleSheet("color: #f2f0eb; font-weight: bold; font-size: 13px;")
            heading.addWidget(name)
            role = QLabel(agent.role)
            role.setStyleSheet("color: #8d969d; font-size: 11px;")
            heading.addWidget(role)
            heading.addStretch(1)
            count = QLabel(tr("{count} tools", count=len(agent.allowed_tools)))
            count.setStyleSheet("color: #9fce20; font-size: 11px;")
            heading.addWidget(count)
            card_layout.addLayout(heading)
            titles = [tool_info(tool).title for tool in agent.allowed_tools] or [tr("no tools")]
            tools = QLabel(" · ".join(titles))
            tools.setWordWrap(True)
            tools.setStyleSheet("color: #c4cec9; font-size: 11px;")
            card_layout.addWidget(tools)
            if agent.approval_tools:
                approval = QLabel(tr(
                    "Requires approval: {tools}",
                    tools=" · ".join(tool_info(tool).title for tool in agent.approval_tools),
                ))
                approval.setWordWrap(True)
                approval.setStyleSheet("color: #ffd166; font-size: 10px;")
                card_layout.addWidget(approval)
            self.tools_agents_layout.addWidget(card)
        # Gateway policies apply to the chat engine; show them only when set.
        for policy in self.engine.gateway.policy_view():
            allowed = policy["allowed_tools"]
            text = tr("POLICY {agent}: {tools}", agent=policy["agent"], tools=", ".join(allowed) if allowed else tr("all"))
            label = QLabel(text)
            label.setStyleSheet("color: #8d969d; font-size: 11px;")
            self.tools_agents_layout.addWidget(label)
        self.tools_agents_layout.addStretch(1)

    _AUDIT_COLORS = {"ok": "#b7ff18", "failed": "#ff6b6b", "approval": "#ffd166"}

    def _refresh_tool_log(self) -> None:
        self.tools_log.clear()
        entries = list(reversed(self.engine.gateway.audit_entries(200)))
        if not entries:
            self.tools_log.addItem(tr("No tool calls logged yet."))
            return
        costs = [entry["cost_usd"] for entry in entries if isinstance(entry.get("cost_usd"), (int, float))]
        if costs:
            total = QListWidgetItem(tr("Tool costs in this log: {total} over {count} paid calls",
                                       total=StatsPanelWidget._money(sum(costs)), count=len(costs)))
            total.setForeground(QColor("#d8ff75"))
            total.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tools_log.addItem(total)
        for entry in entries:
            try:
                moment = datetime.fromisoformat(entry["time"]).astimezone().strftime("%Y-%m-%d  %H:%M:%S")
            except (KeyError, TypeError, ValueError):
                moment = str(entry.get("time", ""))
            status = entry.get("status", "")
            agent = entry.get("agent", "")
            agent_label = "Arqen" if agent in {"", "default"} else agent
            title = tool_info(entry.get("tool", "")).title
            cost = entry.get("cost_usd")
            cost_label = f"  ·  {StatsPanelWidget._money(cost)}" if isinstance(cost, (int, float)) else ""
            item = QListWidgetItem(f"{moment}   {tr(f'audit:{status}'):<12}{title}  ·  {agent_label}{cost_label}")
            item.setForeground(QColor(self._AUDIT_COLORS.get(status, "#c4cec9")))
            item.setToolTip(entry.get("tool", ""))
            self.tools_log.addItem(item)

    def _refresh_memory_view(self) -> None:
        if not hasattr(self, "memory_view_list"):
            return
        records = MemoryStore().records()
        proposals = [record for record in records if record.status == "proposed"]
        kept = [record for record in records if record.status != "proposed"]
        approved = sum(record.status == "approved" for record in kept)
        self.memory_summary.setText(tr(
            "{approved} approved  ·  {proposed} suggested  ·  {obsolete} obsolete",
            approved=approved, proposed=len(proposals), obsolete=len(kept) - approved,
        ))

        self._clear_layout(self.memory_proposals_layout)
        self.memory_proposals_heading.setVisible(bool(proposals))
        self.memory_proposals_host.setVisible(bool(proposals))
        for record in proposals:
            self.memory_proposals_layout.addWidget(self._memory_proposal_card(record))

        selected = self._selected_memory()
        self.memory_view_list.clear()
        # Active memories first; obsolete ones stay visible, dimmed, so they can be restored.
        for record in sorted(kept, key=lambda item: item.status == "obsolete"):
            obsolete = record.status == "obsolete"
            text = f"{record.content}   ({tr('obsolete')})" if obsolete else record.content
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, record.content)
            item.setForeground(QColor("#657078" if obsolete else "#dbe2df"))
            self.memory_view_list.addItem(item)
            if record.content == selected:
                self.memory_view_list.setCurrentItem(item)
        if not kept:
            empty = QListWidgetItem(tr("Nothing approved yet. Say \"kom ihåg att ...\" or approve a suggestion."))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(QColor("#8d969d"))
            self.memory_view_list.addItem(empty)
        self._update_memory_actions()
        self._refresh_memory_badge(len(proposals))

    def _memory_proposal_card(self, record) -> QFrame:
        card = QFrame(objectName="memoryProposal")
        card.setStyleSheet(
            "QFrame#memoryProposal { background: #171d21; border: 1px solid #6b7a2a; border-radius: 8px; }"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 10, 8)
        row.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        content = QLabel(record.content)
        content.setWordWrap(True)
        content.setStyleSheet("color: #f2f0eb; font-size: 12px;")
        text.addWidget(content)
        origin_text = {"arqen": tr("Suggested by Arqen"), "reflect": tr("Suggested after reflection")}
        origin = QLabel(origin_text.get(record.source, tr("Suggested")))
        origin.setStyleSheet("color: #8d969d; font-size: 10px;")
        text.addWidget(origin)
        row.addLayout(text, 1)
        approve = QPushButton(tr("APPROVE"))
        edit = QPushButton(tr("EDIT"))
        reject = QPushButton(tr("REJECT"))
        self._style_page_action(approve, primary=True)
        self._style_page_action(edit)
        self._style_page_action(reject)
        approve.clicked.connect(lambda _, fact=record.content: self._approve_memory(fact))
        edit.clicked.connect(lambda _, fact=record.content: self._edit_memory_text(fact))
        reject.clicked.connect(lambda _, fact=record.content: self._reject_memory(fact))
        for button in (approve, edit, reject):
            row.addWidget(button)
        return card

    def _refresh_memory_badge(self, proposals: int | None = None) -> None:
        """Show on the menu how many memory suggestions wait for a decision."""
        button = getattr(self, "navigation_buttons", {}).get("Memory")
        if button is None:
            return
        if proposals is None:
            proposals = sum(record.status == "proposed" for record in MemoryStore().records())
        label = f"{self._navigation_icons.get('Memory', '')}  {tr('Memory')}"
        button.setText(f"{label}  · {proposals}" if proposals else label)
        # A suggestion made while the view is open should appear without a click.
        if proposals != getattr(self, "_memory_proposals_seen", proposals) and hasattr(self, "memory_proposals_layout"):
            self._memory_proposals_seen = proposals
            self._refresh_memory_view()
            return
        self._memory_proposals_seen = proposals

    def _start_reflection(self) -> None:
        if getattr(self, "reflection_thread", None) is not None:
            return
        self.memory_reflect_button.setEnabled(False)
        self._show_reflection_status(tr("Reflecting on recent tasks and chats..."))

        def run():
            # A provider of its own, like task runs: nothing here touches the chat.
            from arqen.core.reflection import reflect

            provider = create_provider(load_provider_config())
            return reflect(provider, MemoryStore(), getattr(self, "mission_store", None), self.engine.session_store)

        self.reflection_thread = QThread(self)
        self.reflection_worker = ReflectionWorker(run)
        self.reflection_worker.moveToThread(self.reflection_thread)
        self.reflection_thread.started.connect(self.reflection_worker.run)
        self.reflection_worker.finished.connect(self._reflection_finished)
        self.reflection_worker.failed.connect(self._reflection_failed)
        self.reflection_worker.finished.connect(self.reflection_thread.quit)
        self.reflection_worker.failed.connect(self.reflection_thread.quit)
        self.reflection_thread.finished.connect(self.reflection_worker.deleteLater)
        self.reflection_thread.finished.connect(self.reflection_thread.deleteLater)
        self.reflection_thread.finished.connect(self._reflection_thread_finished)
        self.reflection_thread.start()

    def _show_reflection_status(self, text: str) -> None:
        self.memory_reflect_status.setText(text)
        self.memory_reflect_status.show()

    def _reflection_finished(self, result) -> None:
        if not result.had_sources:
            message = tr("Nothing to reflect on yet: no tasks or chats.")
        elif len(result.added) == 1:
            message = tr("Arqen found one new suggestion. Review it below.")
        elif result.added:
            message = tr("Arqen found {count} new suggestions. Review them below.", count=len(result.added))
        else:
            message = tr("No new lessons this time.")
        self._show_reflection_status(message)
        self._refresh_memory_view()

    def _reflection_failed(self, message: str) -> None:
        self._show_reflection_status(tr("Reflection failed: {error}", error=message))

    def _reflection_thread_finished(self) -> None:
        self.reflection_thread = None
        self.reflection_worker = None
        self.memory_reflect_button.setEnabled(True)

    def _approve_memory(self, fact: str) -> None:
        MemoryStore().update(fact, fact, status="approved", confidence=1.0)
        self._refresh_memory_view()

    def _reject_memory(self, fact: str) -> None:
        MemoryStore().forget(fact)
        self._refresh_memory_view()

    def _edit_memory_text(self, old_fact: str) -> None:
        new_fact, accepted = QInputDialog.getMultiLineText(self, tr("Edit memory"), tr("Memory:"), old_fact)
        if accepted and new_fact.strip():
            MemoryStore().update(old_fact, " ".join(new_fact.split()))
            self._refresh_memory_view()

    def _selected_memory(self):
        item = self.memory_view_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_memory_record(self):
        fact = self._selected_memory()
        return next((record for record in MemoryStore().records() if record.content == fact), None) if fact else None

    def _update_memory_actions(self) -> None:
        record = self._selected_memory_record()
        obsolete = record is not None and record.status == "obsolete"
        self.memory_obsolete_button.setText(tr("RESTORE") if obsolete else tr("MARK OBSOLETE"))
        self.memory_obsolete_button.setEnabled(record is not None)

    def _toggle_memory_obsolete(self) -> None:
        record = self._selected_memory_record()
        if record is None:
            return
        status = "approved" if record.status == "obsolete" else "obsolete"
        MemoryStore().update(record.content, record.content, status=status)
        self._refresh_memory_view()

    def _edit_memory_item(self, item=None) -> None:
        old_fact = item.data(Qt.ItemDataRole.UserRole) if item else self._selected_memory()
        if old_fact:
            self._edit_memory_text(old_fact)

    def _delete_memory_item(self) -> None:
        fact = self._selected_memory()
        if not fact:
            return
        answer = QMessageBox.question(self, tr("Delete memory"), tr("Delete this memory?"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            MemoryStore().forget(fact)
            self._refresh_memory_view()

    _CONNECTION_COLUMNS = 3

    def _add_connections_view(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        layout.addWidget(QLabel(tr("CONNECTIONS"), objectName="title"))
        layout.addWidget(QLabel(tr("Give an agent access to a package of tools. More integrations are coming."), objectName="status"))
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel(tr("AGENT"), objectName="sectionLabel"))
        self.connections_agent = QComboBox()
        self.connections_agent.setMinimumWidth(260)
        self.connections_agent.currentIndexChanged.connect(lambda _: self._refresh_connection_cards())
        controls.addWidget(self.connections_agent)
        controls.addStretch(1)
        self.connections_search = QLineEdit()
        self.connections_search.setPlaceholderText(tr("Search connections..."))
        self.connections_search.setClearButtonEnabled(True)
        self.connections_search.setFixedWidth(260)
        self.connections_search.textChanged.connect(lambda _: self._refresh_connection_cards())
        controls.addWidget(self.connections_search)
        add_mcp = QPushButton(tr("+ MCP SERVER"))
        add_mcp.setToolTip(tr("Connect an MCP server: its tools become Arqen tools."))
        self._style_page_action(add_mcp, primary=True)
        add_mcp.clicked.connect(lambda: self._open_mcp_dialog(None))
        controls.addWidget(add_mcp)
        layout.addLayout(controls)
        self.connections_summary = QLabel("")
        self.connections_summary.setStyleSheet("color: #9fce20; font-size: 11px;")
        layout.addWidget(self.connections_summary)
        host = QWidget()
        self.connections_grid = QGridLayout(host)
        self.connections_grid.setContentsMargins(0, 0, 6, 0)
        self.connections_grid.setSpacing(10)
        self.connections_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        self.navigation_stack.addWidget(page)

    def _refresh_connections_view(self) -> None:
        if not hasattr(self, "connections_agent"):
            return
        store = getattr(self, "mission_store", None)
        agents = sorted(store.list_agents(), key=lambda agent: agent.name.lower()) if store is not None else []
        selected = self.connections_agent.currentData()
        self.connections_agent.blockSignals(True)
        self.connections_agent.clear()
        # The chat comes first: it is what the user talks to every day.
        self.connections_agent.addItem(tr("Arqen (the chat)"), self._CHAT_CHOICE)
        for agent in agents:
            self.connections_agent.addItem(f"{agent.name} — {agent.role}", agent.id)
        index = self.connections_agent.findData(selected)
        self.connections_agent.setCurrentIndex(index if index >= 0 else 0)
        self.connections_agent.blockSignals(False)
        self._refresh_connection_cards()

    _CHAT_CHOICE = "__chat__"

    def _selected_connection_agent(self):
        """The chosen agent, or for the chat a stand-in with the chat's current tools."""
        agent_id = self.connections_agent.currentData() if hasattr(self, "connections_agent") else None
        if agent_id == self._CHAT_CHOICE:
            return SimpleNamespace(id=self._CHAT_CHOICE, name="Arqen",
                                   allowed_tools=chat_tools.chat_allowed_tools(self.engine.tools))
        store = getattr(self, "mission_store", None)
        return store.get_agent(agent_id) if store is not None and agent_id else None

    def _refresh_connection_cards(self) -> None:
        if not hasattr(self, "connections_grid"):
            return
        self._clear_layout(self.connections_grid)
        agent = self._selected_connection_agent()
        if agent is None:
            self.connections_summary.setText(tr("No agents yet. Create one under Agents."))
            return
        connectors = all_connectors(self.engine.tools)
        total = sum(len(connector.tools) for connector in connectors)
        granted = sum(tool in agent.allowed_tools for connector in connectors for tool in connector.tools)
        if granted:
            self.connections_summary.setText(tr("{agent} can use {count} of {total} tools.", agent=agent.name, count=granted, total=total))
        else:
            self.connections_summary.setText(tr("{agent} has no tools and can only answer in text.", agent=agent.name))
        query = self.connections_search.text().casefold().strip()
        shown = [
            connector for connector in connectors
            if not query or query in " ".join(
                (connector.name, connector.description, *(tool_info(tool).title for tool in connector.tools))
            ).casefold()
        ]
        if not shown:
            empty = QLabel(tr("No connections match the search."))
            empty.setStyleSheet("color: #8d969d; padding: 12px 2px;")
            self.connections_grid.addWidget(empty, 0, 0)
            return
        for index, connector in enumerate(shown):
            self.connections_grid.addWidget(
                self._connection_card(connector, agent),
                index // self._CONNECTION_COLUMNS, index % self._CONNECTION_COLUMNS,
            )
        for column in range(self._CONNECTION_COLUMNS):
            self.connections_grid.setColumnStretch(column, 1)
        # Spare height goes below the last row, so cards keep their natural size.
        rows = (len(shown) + self._CONNECTION_COLUMNS - 1) // self._CONNECTION_COLUMNS
        for row in range(self.connections_grid.rowCount()):
            self.connections_grid.setRowStretch(row, 1 if row == rows else 0)
        self.connections_grid.setRowStretch(rows, 1)

    def _connection_card(self, connector, agent) -> QFrame:
        state = grant_state(connector, agent.allowed_tools)
        border = {GrantState.FULL: "#b7ff18", GrantState.PARTIAL: "#6b7a2a"}.get(state, "#30383a")
        card = QFrame(objectName="connectionCard")
        card.setStyleSheet(f"QFrame#connectionCard {{ background: #171d21; border: 1px solid {border}; border-radius: 8px; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(4)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        badge = QLabel(connector.badge)
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("color: #d8ff75; background: #111516; border: 1px solid #30383a; border-radius: 6px; font-weight: bold;")
        heading.addWidget(badge)
        name = QLabel(connector.name)
        name.setStyleSheet("color: #f2f0eb; font-weight: bold; font-size: 13px;")
        heading.addWidget(name)
        heading.addStretch(1)
        if connector.builtin:
            chip_text, chip_color = tr("BUILT-IN"), "#8d969d"
        elif not connector.is_connected():
            chip_text, chip_color = tr("NOT CONNECTED"), "#8d969d"
        elif connector.needs_reconnect():
            chip_text, chip_color = tr("NEEDS RECONNECTING"), "#ff9f1c"
        elif connector.is_paused():
            chip_text, chip_color = tr("PAUSED"), "#ffd166"
        else:
            chip_text, chip_color = tr("CONNECTED"), "#b7ff18"
        chip = QLabel(chip_text)
        chip.setStyleSheet(f"color: {chip_color}; border: 1px solid {chip_color}; border-radius: 8px; padding: 1px 7px; font-size: 9px;")
        heading.addWidget(chip)
        card_layout.addLayout(heading)
        if not connector.builtin:
            reconnect = connector.needs_reconnect()
            if reconnect:
                manage = QPushButton(tr("RECONNECT"))
            else:
                manage = QPushButton(tr("MANAGE") if connector.is_connected() else tr("+ CONNECT"))
            self._style_page_action(manage, primary=reconnect or not connector.is_connected())
            if connector.auth == "mcp":
                manage.clicked.connect(lambda _, cid=connector.id: self._open_mcp_dialog(cid))
            else:
                manage.clicked.connect(lambda _, item=connector: self._open_connector_dialog(item))
            card_layout.addWidget(manage, alignment=Qt.AlignmentFlag.AlignLeft)

        description = QLabel(connector.description)
        description.setWordWrap(True)
        description.setStyleSheet("color: #c4cec9; font-size: 11px;")
        card_layout.addWidget(description)
        titles = [tool_info(tool).title for tool in connector.tools]
        # An MCP server can bring hundreds of tools; the card shows the first few.
        shown_titles = " · ".join(titles[:10]) + (f" · +{len(titles) - 10}" if len(titles) > 10 else "")
        tools = QLabel(shown_titles or tr("No tools fetched yet."))
        tools.setWordWrap(True)
        tools.setStyleSheet("color: #657078; font-size: 10px;")
        card_layout.addWidget(tools)
        card_layout.addStretch(1)

        footer = QHBoxLayout()
        count = sum(tool in agent.allowed_tools for tool in connector.tools)
        status_text = {
            GrantState.FULL: tr("All {count} tools", count=len(connector.tools)),
            GrantState.PARTIAL: tr("{count} of {total} tools", count=count, total=len(connector.tools)),
            GrantState.NONE: tr("{count} tools", count=len(connector.tools)),
        }[state]
        status = QLabel(status_text)
        status.setStyleSheet(f"color: {'#9fce20' if state is not GrantState.NONE else '#8d969d'}; font-size: 10px;")
        footer.addWidget(status)
        footer.addStretch(1)
        if state is not GrantState.FULL:
            grant = QPushButton(tr("GIVE {agent} ACCESS", agent=agent.name.upper()) if state is GrantState.NONE else tr("GIVE ALL"))
            self._style_page_action(grant, primary=True)
            grant.clicked.connect(lambda _, cid=connector.id: self._set_connector_access(cid, True))
            footer.addWidget(grant)
        if state is not GrantState.NONE:
            remove = QPushButton(tr("REMOVE"))
            self._style_page_action(remove)
            remove.clicked.connect(lambda _, cid=connector.id: self._set_connector_access(cid, False))
            footer.addWidget(remove)
        card_layout.addLayout(footer)
        return card

    def _open_connector_dialog(self, connector) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("{name} – connection", name=connector.name))
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        intro = QLabel(connector.description)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        saved = connector_store.load_credentials(connector.id)
        inputs: dict[str, QLineEdit] = {}
        lookups: list[tuple[QPushButton, object]] = []
        for item in connector.fields:
            field_input = QLineEdit(saved.get(item.name, ""))
            field_input.setPlaceholderText(item.placeholder)
            if item.secret:
                field_input.setEchoMode(QLineEdit.EchoMode.Password)
            if item.lookup is not None:
                row = QHBoxLayout()
                row.addWidget(field_input, 1)
                lookup_button = QPushButton(tr(item.lookup_label))
                self._style_page_action(lookup_button)
                lookup_button.setAutoDefault(False)
                row.addWidget(lookup_button)
                form.addRow(item.label, row)
                lookups.append((lookup_button, item))
            else:
                form.addRow(item.label, field_input)
            if item.help:
                hint = QLabel(item.help)
                hint.setWordWrap(True)
                hint.setStyleSheet("color: #8d969d; font-size: 11px;")
                form.addRow("", hint)
            inputs[item.name] = field_input
        layout.addLayout(form)
        settings = connector_store.load_settings(connector.id)
        oauth = connector.auth == "oauth" and connector.sign_in is not None
        account = QLabel("")
        account.setWordWrap(True)
        sign_in_button = QPushButton(tr("SIGN IN WITH {name}", name=connector.name.upper()))
        if oauth:
            sign_in_row = QHBoxLayout()
            sign_in_row.addWidget(account, 1)
            sign_in_row.addWidget(sign_in_button)
            layout.addLayout(sign_in_row)
        notify = None
        if connector.notify is not None:
            notify = QCheckBox(tr("Notify here when tasks finish or fail"))
            notify.setChecked(bool(settings.get("notify", False)))
            layout.addWidget(notify)
        paused = QCheckBox(tr("Pause the connection (agents cannot use it)"))
        paused.setChecked(bool(settings.get("paused", False)))
        layout.addWidget(paused)
        result = QLabel("")
        result.setWordWrap(True)
        layout.addWidget(result)

        def values() -> dict[str, str]:
            return {name: field_input.text().strip() for name, field_input in inputs.items()}

        def run_lookup(item) -> None:
            current = values()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                found = item.lookup(current)
            except Exception as exc:
                result.setStyleSheet("color: #ff6b6b;")
                result.setText(tr("Did not work: {error}", error=self._scrub(str(exc), current)))
                return
            finally:
                QApplication.restoreOverrideCursor()
            if not found:
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("No messages to the bot yet. Write something to it in Telegram and try again. "
                                  "If another program reads the bot (e.g. monitoring), use @userinfobot instead."))
                return
            value = found[0][0]
            if len(found) > 1:
                choices = [f"{label}  ·  {chat}" for chat, label in found]
                choice, ok = QInputDialog.getItem(dialog, tr(item.lookup_label), tr("Which chat should Arqen use?"), choices, 0, False)
                if not ok:
                    return
                value = found[choices.index(choice)][0]
            inputs[item.name].setText(value)
            result.setStyleSheet("color: #b7ff18;")
            result.setText(tr("Filled in: {value}. Press TEST CONNECTION and SAVE.", value=value))

        for lookup_button, item in lookups:
            lookup_button.clicked.connect(lambda _, field=item: run_lookup(field))

        def issued() -> dict[str, str]:
            """What the sign-in stored, as long as it belongs to the typed-in client."""
            stored = connector_store.load_credentials(connector.id)
            if any(stored.get(name, "") != value for name, value in values().items()):
                return {}
            return {name: stored[name] for name in connector.issued if stored.get(name)}

        def show_account() -> None:
            current = connector_store.load_settings(connector.id)
            if issued() and current.get("needs_reconnect"):
                account.setStyleSheet("color: #ff9f1c;")
                account.setText(tr("The sign-in has expired or was revoked. Press {button} again.",
                                   button=tr("SIGN IN WITH {name}", name=connector.name.upper())))
            elif issued() and current.get("account"):
                account.setStyleSheet("color: #b7ff18;")
                account.setText(tr("Signed in as {account}.", account=current["account"]))
            elif issued():
                account.setStyleSheet("color: #b7ff18;")
                account.setText(tr("Signed in."))
            else:
                account.setStyleSheet("color: #8d969d;")
                account.setText(tr("Not signed in. Fill in the client and press {button}.",
                                   button=tr("SIGN IN WITH {name}", name=connector.name.upper())))

        def test() -> None:
            current = values()
            if oauth and all(current.values()) and not issued():
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("Sign in first."))
                return
            current = {**current, **issued()} if oauth else current
            if not all(current.values()):
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("Fill in every field first."))
                return
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                reached = connector.test(current) if connector.test else ""
                result.setStyleSheet("color: #b7ff18;")
                result.setText(tr("Works: {reached}", reached=reached))
            except Exception as exc:
                result.setStyleSheet("color: #ff6b6b;")
                result.setText(tr("Did not work: {error}", error=self._scrub(str(exc), current)))
            finally:
                QApplication.restoreOverrideCursor()

        def save() -> None:
            current = values()
            if not all(current.values()):
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("Fill in every field first."))
                return
            # A changed OAuth client needs a new sign-in; the old grant is dropped.
            connector_store.save_credentials(connector.id, {**current, **issued()} if oauth else current)
            changes = {"paused": paused.isChecked()}
            if notify is not None:
                changes["notify"] = notify.isChecked()
            connector_store.save_settings(connector.id, **changes)
            dialog.accept()

        def disconnect() -> None:
            answer = QMessageBox.question(
                dialog, tr("Disconnect"), tr("Remove the saved credentials for {name}?", name=connector.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                if connector.sign_out is not None:
                    # Withdrawing the grant at the service must not hold up the dialog.
                    threading.Thread(target=connector.sign_out, args=(connector_store.load_credentials(connector.id),),
                                     daemon=True, name="arqen-sign-out").start()
                connector_store.forget_credentials(connector.id)
                dialog.accept()

        cancel_sign_in = threading.Event()
        sign_in_state: dict = {}
        sign_in_timer = QTimer(dialog)

        def sign_in() -> None:
            current = values()
            if not all(current.values()):
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("Fill in every field first."))
                return
            sign_in_state.clear()
            cancel_sign_in.clear()

            def work() -> None:
                try:
                    sign_in_state["issued"] = connector.sign_in(current, cancel=cancel_sign_in)
                except Exception as exc:
                    sign_in_state["error"] = str(exc)

            # Saving or testing closes or races the wait; the sign-in saves by itself.
            for button in (sign_in_button, test_button, save_button):
                button.setEnabled(False)
            result.setStyleSheet("color: #d8ff75;")
            result.setText(tr("The browser opens {name}. Approve the access there; Arqen waits here.", name=connector.name))
            threading.Thread(target=work, daemon=True, name="arqen-sign-in").start()
            sign_in_timer.start(250)

        def sign_in_done() -> None:
            if not sign_in_state:
                return
            sign_in_timer.stop()
            for button in (sign_in_button, test_button, save_button):
                button.setEnabled(True)
            current = values()
            if "error" in sign_in_state:
                result.setStyleSheet("color: #ff6b6b;")
                result.setText(tr("Did not work: {error}", error=self._scrub(sign_in_state["error"], current)))
                return
            granted = dict(sign_in_state["issued"])
            details = granted.pop("settings", {})
            missing = granted.pop("missing", [])
            connector_store.save_credentials(connector.id, {**current, **granted})
            connector_store.save_settings(connector.id, paused=paused.isChecked(), **details)
            show_account()
            if missing:
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("Connected, but without access to: {scopes}. Those tools will fail until you sign in again and tick them.",
                                  scopes=", ".join(missing)))
            else:
                result.setStyleSheet("color: #b7ff18;")
                result.setText(tr("Connected. The tools can be used now."))

        sign_in_timer.timeout.connect(sign_in_done)
        dialog.finished.connect(lambda _: cancel_sign_in.set())

        buttons = QHBoxLayout()
        if oauth:
            show_account()
            self._style_page_action(sign_in_button, primary=True)
            sign_in_button.clicked.connect(sign_in)
            sign_in_button.setAutoDefault(False)
            if connector.help_url:
                guide = QLabel(f'<a href="{connector.help_url}" style="color: #9fce20;">{tr("Open the setup page for {name}", name=connector.name)}</a>')
                guide.setOpenExternalLinks(True)
                layout.insertWidget(1, guide)
        test_button = QPushButton(tr("TEST CONNECTION"))
        save_button = QPushButton(tr("SAVE"))
        self._style_page_action(test_button)
        self._style_page_action(save_button, primary=True)
        test_button.clicked.connect(test)
        save_button.clicked.connect(save)
        buttons.addWidget(test_button)
        if connector.is_connected():
            disconnect_button = QPushButton(tr("DISCONNECT"))
            self._style_page_action(disconnect_button)
            disconnect_button.clicked.connect(disconnect)
            buttons.addWidget(disconnect_button)
        buttons.addStretch(1)
        close = QPushButton(tr("CLOSE"))
        self._style_page_action(close)
        close.clicked.connect(dialog.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        for button in (test_button, save_button, close):
            button.setAutoDefault(False)
        dialog.exec()
        self._refresh_connection_cards()
        if hasattr(self, "tools_stack"):
            self._refresh_tools_view()

    def _open_mcp_dialog(self, connector_id: str | None) -> None:
        servers = mcp_servers.load_servers()
        server = next((item for item in servers if mcp_servers.connector_id(item) == connector_id), None)
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("MCP server") if server is None else tr("{name} – connection", name=server.get("name", "")))
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        intro = QLabel(tr("An MCP server gives Arqen more tools. Its tools ask for approval unless the server marks them as read-only."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        name = QLineEdit(str((server or {}).get("name", "")))
        name.setPlaceholderText(tr("e.g. Zapier"))
        form.addRow(tr("Name"), name)
        transport = QComboBox()
        transport.addItem(tr("Address (HTTP)"), "http")
        transport.addItem(tr("Local program"), "stdio")
        transport.setCurrentIndex(max(0, transport.findData((server or {}).get("transport", "http"))))
        form.addRow(tr("Type"), transport)
        url = QLineEdit(str((server or {}).get("url", "")))
        url.setPlaceholderText("https://…/mcp")
        form.addRow(tr("Address"), url)
        token = QLineEdit(mcp_servers.server_token(server) if server else "")
        token.setEchoMode(QLineEdit.EchoMode.Password)
        token.setPlaceholderText(tr("Only if the server asks for one"))
        form.addRow(tr("Token (optional)"), token)
        command = QLineEdit(str((server or {}).get("command", "")))
        command.setPlaceholderText("npx")
        form.addRow(tr("Program"), command)
        args = QLineEdit(str((server or {}).get("args", "")))
        args.setPlaceholderText("-y @modelcontextprotocol/server-everything")
        form.addRow(tr("Arguments"), args)
        layout.addLayout(form)
        warning = QLabel(tr("A local program runs on this computer with your permissions. Only add programs you trust."))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #ffd166; font-size: 11px;")
        layout.addWidget(warning)
        paused = QCheckBox(tr("Pause the connection (agents cannot use it)"))
        if server is not None:
            paused.setChecked(bool(connector_store.load_settings(mcp_servers.connector_id(server)).get("paused", False)))
            layout.addWidget(paused)
        result = QLabel("")
        result.setWordWrap(True)
        layout.addWidget(result)
        fetched: dict[str, list] = {}

        def update_fields() -> None:
            local = transport.currentData() == "stdio"
            for widget in (url, token):
                widget.setEnabled(not local)
            for widget in (command, args):
                widget.setEnabled(local)
            warning.setVisible(local)

        transport.currentIndexChanged.connect(lambda _: update_fields())
        update_fields()

        def draft() -> dict:
            base = dict(server or {})
            base.update({
                "name": name.text().strip(), "transport": transport.currentData(),
                "url": url.text().strip(), "command": command.text().strip(), "args": args.text().strip(),
            })
            base.setdefault("id", "draft")
            return base

        def fetch() -> bool:
            current = draft()
            if not current["name"] or not (current["url"] if current["transport"] == "http" else current["command"]):
                result.setStyleSheet("color: #ffd166;")
                result.setText(tr("Fill in a name and an address or program first."))
                return False
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                specs = mcp_servers.fetch_tools(current, token.text().strip())
                fetched["tools"] = [spec.to_json() for spec in specs]
                read_only = sum(spec.read_only for spec in specs)
                result.setStyleSheet("color: #b7ff18;")
                result.setText(tr("Works: {count} tools ({read_only} read-only).", count=len(specs), read_only=read_only))
                return True
            except Exception as exc:
                result.setStyleSheet("color: #ff6b6b;")
                result.setText(tr("Did not work: {error}", error=self._scrub(str(exc), {"token": token.text()})))
                return False
            finally:
                QApplication.restoreOverrideCursor()

        def save() -> None:
            if "tools" not in fetched and not fetch():
                return
            current = draft()
            others = [item for item in servers if server is None or item["id"] != server["id"]]
            if server is None:
                current["id"] = mcp_servers.server_id(current["name"], {item["id"] for item in servers})
            current["tools"] = fetched["tools"]
            mcp_servers.save_servers(others + [current])
            cid = mcp_servers.connector_id(current)
            if current["transport"] == "http" and token.text().strip():
                connector_store.save_credentials(cid, {"token": token.text().strip()})
            else:
                connector_store.forget_credentials(cid)
            connector_store.save_settings(cid, paused=paused.isChecked())
            dialog.accept()

        def remove() -> None:
            answer = QMessageBox.question(
                dialog, tr("Remove server"), tr("Remove {name} and its tools from Arqen?", name=server.get("name", "")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            mcp_servers.save_servers([item for item in servers if item["id"] != server["id"]])
            cid = mcp_servers.connector_id(server)
            connector_store.forget_credentials(cid)
            # Agents keep no stale names of tools that no longer exist.
            prefix = mcp_servers.tool_name(server, "")
            for agent in self.mission_store.list_agents():
                kept = tuple(tool for tool in agent.allowed_tools if not tool.startswith(prefix))
                if kept != agent.allowed_tools:
                    approvals = tuple(tool for tool in agent.approval_tools if tool in kept)
                    self.mission_store.save_agent(replace_dataclass(agent, allowed_tools=kept, approval_tools=approvals))
            dialog.accept()

        buttons = QHBoxLayout()
        test_button = QPushButton(tr("TEST AND FETCH TOOLS"))
        save_button = QPushButton(tr("SAVE"))
        self._style_page_action(test_button)
        self._style_page_action(save_button, primary=True)
        test_button.clicked.connect(fetch)
        save_button.clicked.connect(save)
        buttons.addWidget(test_button)
        if server is not None:
            remove_button = QPushButton(tr("REMOVE SERVER"))
            self._style_page_action(remove_button)
            remove_button.clicked.connect(remove)
            buttons.addWidget(remove_button)
        buttons.addStretch(1)
        close = QPushButton(tr("CLOSE"))
        self._style_page_action(close)
        close.clicked.connect(dialog.reject)
        buttons.addWidget(save_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        for button in (test_button, save_button, close):
            button.setAutoDefault(False)
        dialog.exec()
        # New or removed tools reach the chat right away; task engines pick them up on their own.
        mcp_servers.sync_mcp_tools(self.engine.tools)
        self._refresh_connection_cards()
        self.refresh_mission_agents()
        if hasattr(self, "tools_stack"):
            self._refresh_tools_view()

    @staticmethod
    def _scrub(text: str, credentials: dict[str, str]) -> str:
        """Keep typed-in credentials out of any message shown on screen."""
        for value in credentials.values():
            if len(value) >= 6:
                text = text.replace(value, "••••")
        return text

    def _notify_task_changes(self) -> None:
        """Tell connected Discord/Telegram when a task finishes or fails, if asked to."""
        store = getattr(self, "mission_store", None)
        if store is None:
            return
        tasks = store.list_tasks()
        seen = getattr(self, "_task_status_seen", None)
        self._task_status_seen = {task.id: task.status for task in tasks}
        if seen is None:
            return  # the first look only remembers; old tasks are not announced
        finished = [task for task in tasks if task.status in {"completed", "failed"} and seen.get(task.id) != task.status]
        targets = [
            connector for connector in EXTERNAL
            if connector.notify is not None and connector.is_active()
            and connector_store.load_settings(connector.id).get("notify", False)
        ]
        if not finished or not targets:
            return
        lines = []
        for task in finished:
            agent = store.get_agent(task.agent_id) if task.agent_id else None
            who = f" ({agent.name})" if agent else ""
            if task.status == "completed":
                lines.append(tr("Done: {title}{who}", title=task.title, who=who))
            else:
                lines.append(tr("Failed: {title}{who} – {error}", title=task.title, who=who, error=(task.error or "")[:200]))
        message = "Arqen\n" + "\n".join(lines)
        jobs = [(connector.notify, connector_store.load_credentials(connector.id)) for connector in targets]

        def send() -> None:
            for notify, credentials in jobs:
                try:
                    notify(credentials, message)
                except Exception as exc:
                    # A failed notice must never disturb the app; it only goes to the console.
                    print(f"Notification failed: {type(exc).__name__}", flush=True)

        threading.Thread(target=send, daemon=True, name="arqen-notify").start()

    def _check_sign_ins(self) -> None:
        """Try each browser sign-in once at start, so an expired one shows before it is needed."""
        checks = [(connector.test, connector_store.load_credentials(connector.id)) for connector in EXTERNAL
                  if connector.auth == "oauth" and connector.test is not None and connector.is_active()]

        def run() -> None:
            for test, credentials in checks:
                try:
                    test(credentials)  # an expired grant marks itself; the badge picks it up
                except Exception as exc:
                    print(f"Sign-in check failed: {type(exc).__name__}", flush=True)

        if checks:
            threading.Thread(target=run, daemon=True, name="arqen-sign-in-check").start()

    def _refresh_connections_badge(self) -> None:
        """Show on the menu how many connections have to be signed in again."""
        button = getattr(self, "navigation_buttons", {}).get("Connections")
        if button is None:
            return
        count = sum(connector.needs_reconnect() for connector in EXTERNAL)
        label = f"{self._navigation_icons.get('Connections', '')}  {tr('Connections')}"
        button.setText(f"{label}  · {count}" if count else label)
        button.setToolTip((tr("A connection needs to be signed in again.") if count == 1 else tr("{count} connections need to be signed in again.", count=count)) if count else "")
        # The cards follow as soon as the state changes, even with the view open.
        if count != getattr(self, "_reconnect_count_seen", count):
            self._refresh_connection_cards()
        self._reconnect_count_seen = count

    def _set_connector_access(self, connector_id: str, grant: bool) -> None:
        agent = self._selected_connection_agent()
        connector = next((item for item in all_connectors(self.engine.tools) if item.id == connector_id), None)
        if agent is None or connector is None:
            return
        change = with_connector if grant else without_connector
        tools = change(connector, agent.allowed_tools)
        if agent.id == self._CHAT_CHOICE:
            # The chat keeps what it lost, not what it has, so new tools reach it by default.
            everything = [item["name"] for item in self.engine.tools.describe()]
            chat_tools.save_denied_tools(name for name in everything if name not in tools)
            chat_tools.apply_chat_tool_limits(self.engine)
            self._refresh_connection_cards()
            return
        # Approval rules only make sense for tools the agent still has.
        approvals = tuple(tool for tool in agent.approval_tools if tool in tools)
        self.mission_store.save_agent(replace_dataclass(agent, allowed_tools=tools, approval_tools=approvals))
        self._refresh_connection_cards()
        self.refresh_mission_agents()
        if hasattr(self, "tools_stack"):
            self._refresh_tools_view()

    def _add_content_view(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(QLabel(tr("CONTENT"), objectName="title"))
        page_layout.addWidget(QLabel(tr("Generated files and workflow artifacts.")))
        self.content_view_list = QListWidget()
        page_layout.addWidget(self.content_view_list, 1)
        refresh = QPushButton(tr("REFRESH CONTENT"))
        self._style_page_action(refresh)
        refresh.clicked.connect(self._refresh_content_view)
        page_layout.addWidget(refresh)
        self._refresh_content_view()
        self.navigation_stack.addWidget(page)

    def _refresh_content_view(self) -> None:
        if not hasattr(self, "content_view_list"):
            return
        self.content_view_list.clear()
        root = paths.data_dir()
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.name != "mission.sqlite3":
                    self.content_view_list.addItem(str(path.relative_to(root)))

    def _add_navigation_button(self, layout: QVBoxLayout, label: str, icon: str) -> None:
        button = QPushButton(f"{icon}  {tr(label)}")
        if not hasattr(self, "_navigation_icons"):
            self._navigation_icons: dict[str, str] = {}
        self._navigation_icons[label] = icon
        button.setObjectName("navButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _, name=label: self._select_navigation(name))
        layout.addWidget(button)
        self.navigation_buttons[label] = button

    def _select_navigation(self, name: str) -> None:
        self.status.setText(self.provider_status(tr(name).upper()))
        for label, button in getattr(self, "navigation_buttons", {}).items():
            button.setProperty("active", label == name)
            button.setStyleSheet(
                "QPushButton { background: #171d21; color: #dbe2df; border: none; "
                "border-left: 2px solid #b7ff18; text-align: left; padding: 7px 8px; border-radius: 5px; }"
                if label == name else
                "QPushButton { background: transparent; color: #8d969d; border: none; "
                "text-align: left; padding: 7px 8px; border-radius: 5px; }"
            )
        pages = {"Dashboard": 0, "Chat": 1, "Tasks": 2, "Workflows": 3, "Schedules": 4, "Agents": 5, "Activity": 6, "Memory": 7, "Tools": 8, "Content": 9, "Connections": 10, "Mission Control": getattr(self, "mission_page_index", 0)}
        if name in pages and hasattr(self, "navigation_stack"):
            self.navigation_stack.setCurrentIndex(pages[name])
            if name == "Memory":
                self._refresh_memory_view()
            elif name == "Tools":
                self._refresh_tools_view()
            elif name == "Content":
                self._refresh_content_view()
            elif name == "Connections":
                self._refresh_connections_view()

    def _create_mission_dock(self) -> None:
        """Create the first functional Mission Control surface."""
        # Looked up through the module so tests that redirect the data
        # directory keep their tasks out of the real mission database.
        self.mission_store = MissionStore(paths.data_dir() / "mission.sqlite3")
        self.mission_runner = MissionRunner(self.mission_store, self._new_task_engine)
        self.workflow_runner = WorkflowRunner(self.mission_store, self.mission_runner)
        self.scheduler_worker = SchedulerWorker(MissionScheduler(self.mission_store, self.workflow_runner))
        self.scheduler_worker.start()
        self.task_worker = TaskWorker(self.mission_store, self.mission_runner)
        self.task_worker.start()
        dock = QDockWidget(tr("MISSION CONTROL"), self)
        dock.setObjectName("missionControlDock")
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(QLabel(tr("WORKFLOWS")))
        legacy_workflows = QListWidget()
        panel_layout.addWidget(legacy_workflows)
        legacy_workflow_runs = QListWidget()
        panel_layout.addWidget(legacy_workflow_runs)
        workflow_row = QHBoxLayout()
        new_workflow = QPushButton(tr("NEW WORKFLOW"))
        run_workflow = QPushButton(tr("RUN WORKFLOW"))
        resume_workflow = QPushButton(tr("RESUME RUN"))
        new_workflow.clicked.connect(self._create_mission_workflow)
        run_workflow.clicked.connect(self._run_mission_workflow)
        resume_workflow.clicked.connect(self._resume_mission_workflow)
        for button in (new_workflow, run_workflow, resume_workflow):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button, primary=button is new_workflow)
            workflow_row.addWidget(button)
        workflow_row.addStretch(1)
        panel_layout.addLayout(workflow_row)
        panel_layout.addWidget(QLabel(tr("ACTIVITY")))
        self.mission_activity = QListWidget()
        self.mission_activity.itemClicked.connect(self._open_activity_task)
        panel_layout.addWidget(self.mission_activity)
        self.mission_activity_timer = QTimer(self)
        self.mission_activity_timer.setInterval(2000)
        self.mission_activity_timer.timeout.connect(self.refresh_mission_activity)
        self.mission_activity_timer.timeout.connect(self.refresh_dashboard)
        self.mission_activity_timer.timeout.connect(self.refresh_mission_tasks)
        self.mission_activity_timer.timeout.connect(self.refresh_mission_approvals)
        self.mission_activity_timer.timeout.connect(self._refresh_approval_bar)
        self.mission_activity_timer.timeout.connect(lambda: self._refresh_memory_badge())
        self.mission_activity_timer.timeout.connect(self._notify_task_changes)
        self.mission_activity_timer.timeout.connect(self._refresh_connections_badge)
        self.mission_activity_timer.start()
        self._check_sign_ins()
        panel_layout.addWidget(QLabel(tr("SCHEDULES")))
        legacy_schedules = QListWidget()
        panel_layout.addWidget(legacy_schedules)
        schedule_row = QHBoxLayout()
        new_schedule = QPushButton(tr("NEW SCHEDULE"))
        toggle_schedule = QPushButton(tr("ENABLE/DISABLE"))
        new_schedule.clicked.connect(self._create_mission_schedule)
        toggle_schedule.clicked.connect(self._toggle_mission_schedule)
        for button in (new_schedule, toggle_schedule):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button, primary=button is new_schedule)
            schedule_row.addWidget(button)
        schedule_row.addStretch(1)
        panel_layout.addLayout(schedule_row)
        panel_layout.addWidget(QLabel(tr("AGENTS")))
        legacy_agents = QListWidget()
        panel_layout.addWidget(legacy_agents)
        agent_row = QHBoxLayout()
        new_agent = QPushButton(tr("NEW AGENT"))
        edit_agent = QPushButton(tr("EDIT"))
        toggle_agent = QPushButton(tr("ENABLE/DISABLE"))
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
        panel_layout.addWidget(QLabel(tr("PENDING APPROVALS")))
        legacy_approvals = QListWidget()
        legacy_approvals.itemClicked.connect(self._show_selected_approval)
        panel_layout.addWidget(legacy_approvals)
        approval_row = QHBoxLayout()
        approve = QPushButton(tr("APPROVE"))
        reject = QPushButton(tr("REJECT"))
        approve.clicked.connect(lambda: self._decide_mission_approval("approved"))
        reject.clicked.connect(lambda: self._decide_mission_approval("rejected"))
        approval_row.addWidget(approve)
        approval_row.addWidget(reject)
        panel_layout.addLayout(approval_row)
        create = QPushButton(tr("NEW TASK"))
        create.clicked.connect(self._create_mission_task)
        run = QPushButton(tr("RUN SELECTED TASK"))
        run.clicked.connect(self._run_mission_task)
        retry = QPushButton(tr("RETRY"))
        retry.clicked.connect(self._retry_mission_task)
        legacy_details = QTextEdit(readOnly=True)
        legacy_details.setPlaceholderText(tr("Select a task to view status and events."))
        panel_layout.addWidget(legacy_details)
        panel_layout.addWidget(create)
        panel_layout.addWidget(run)
        panel_layout.addWidget(retry)
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.mission_dock = dock
        mission_page = dock.widget()
        dock.setWidget(None)
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(18, 18, 18, 18)
        overview_layout.setSpacing(12)
        overview_layout.addWidget(QLabel(tr("MISSION CONTROL"), objectName="title"))
        overview_layout.addWidget(QLabel(tr("Operational queue // decide what should happen next."), objectName="status"))
        overview_cards = QGridLayout()
        overview_cards.setSpacing(10)
        self.mission_overview_cards: dict[str, QLabel] = {}
        for index, (key, label, target) in enumerate((
            ("queue", "TASK QUEUE", "Tasks"),
            ("approvals", "WAITING APPROVAL", "Pending Approvals"),
            ("workflows", "ACTIVE WORKFLOWS", "Workflows"),
            ("attention", "NEEDS ATTENTION", "Attention Tasks"),
        )):
            card = QFrame(objectName="panel")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.mousePressEvent = lambda event, name=target: (
                self._open_attention_tasks() if name == "Attention Tasks" else
                self._open_pending_approvals() if name == "Pending Approvals" else
                self._select_navigation(name)
            )
            card.setMinimumHeight(92)
            card.setStyleSheet(
                "QFrame#panel { background: #111516; border: 1px solid #3b4748; border-radius: 8px; }"
                "QFrame#panel:hover { background: #171d21; border: 1px solid #b7ff18; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.addWidget(QLabel(tr(label)))
            value = QLabel("0", objectName="title")
            value.setStyleSheet("color: #d8ff75; font-size: 26px; font-weight: 700;")
            card_layout.addWidget(value)
            self.mission_overview_cards[key] = value
            overview_cards.addWidget(card, index // 2, index % 2)
        overview_layout.addLayout(overview_cards)
        overview_layout.addWidget(QLabel(tr("LATEST ACTIVITY"), objectName="sectionLabel"))
        self.mission_overview_activity = QListWidget()
        self.mission_overview_activity.setSpacing(4)
        self.mission_overview_activity.setStyleSheet(
            "QListWidget { background: #111516; border: 1px solid #30383a; border-radius: 8px; padding: 6px; }"
            "QListWidget::item { padding: 8px; border-bottom: 1px solid #252d30; color: #c4cec9; }"
        )
        self.mission_overview_activity.setMaximumHeight(300)
        overview_layout.addWidget(self.mission_overview_activity)
        overview_actions = QHBoxLayout()
        for label, target in (("OPEN TASKS", "Tasks"), ("OPEN WORKFLOWS", "Workflows"), ("OPEN ACTIVITY", "Activity")):
            button = QPushButton(tr(label))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_page_action(button, primary=target == "Tasks")
            button.clicked.connect(lambda _, name=target: self._select_navigation(name))
            overview_actions.addWidget(button)
        overview_actions.addStretch(1)
        overview_layout.addLayout(overview_actions)
        overview_layout.addStretch(1)
        self.mission_page_index = self.navigation_stack.addWidget(overview)
        dock.hide()
        self.refresh_mission_tasks()
        self.refresh_mission_approvals()
        self.refresh_mission_agents()
        self.refresh_mission_schedules()
        self.refresh_mission_workflows()
        self.refresh_mission_workflow_runs()
        self.refresh_mission_activity()
        self.refresh_dashboard()

    def _new_task_engine(self) -> ConversationEngine:
        """A separate engine for each task, built from the saved settings.

        Tasks used to borrow the chat engine.  An agent's run then narrowed its
        tool list and approval rules for good, so the chat lost tools until a
        restart, and task prompts landed in whatever chat was open.
        """
        return ConversationEngine(
            provider=create_provider(load_provider_config()),
            tools=create_builtin_registry(),
        )

    def refresh_dashboard(self) -> None:
        if not hasattr(self, "dashboard_cards"):
            return
        self.dashboard_cards["agents"].setText(str(len(self.mission_store.list_agents())))
        active = sum(1 for task in self.mission_store.list_tasks() if task.status in {"queued", "running", "waiting_approval"})
        self.dashboard_cards["tasks"].setText(str(active))
        self.dashboard_cards["approvals"].setText(str(len(self.mission_store.list_approvals("pending"))))
        self.dashboard_cards["workflows"].setText(str(len(self.mission_store.list_workflow_runs())))
        if hasattr(self, "mission_overview_cards"):
            tasks = self.mission_store.list_tasks()
            active_workflows = sum(1 for run in self.mission_store.list_workflow_runs() if run.status in {"queued", "running", "waiting_approval"})
            attention = sum(1 for task in tasks if task.status in {"failed", "cancelled"})
            self.mission_overview_cards["queue"].setText(str(sum(1 for task in tasks if task.status in {"queued", "running"})))
            self.mission_overview_cards["approvals"].setText(str(len(self.mission_store.list_approvals("pending"))))
            self.mission_overview_cards["workflows"].setText(str(active_workflows))
            self.mission_overview_cards["attention"].setText(str(attention))
        self.dashboard_activity.clear()
        if hasattr(self, "mission_overview_activity"):
            self.mission_overview_activity.clear()
        for event in self.mission_store.list_all_events(8):
            text = f"[{status_label(event.kind)}] {tr(event.message)}"
            self.dashboard_activity.addItem(text)
            if hasattr(self, "mission_overview_activity"):
                self.mission_overview_activity.addItem(text)
        if hasattr(self, "mission_overview_activity") and not self.mission_overview_activity.count():
            self.mission_overview_activity.addItem(tr("No recent activity"))

    def refresh_mission_activity(self) -> None:
        target = getattr(self, "activity_view_list", self.mission_activity)
        target.clear()
        latest_by_task = {}
        for event in self.mission_store.list_all_events(80):
            # Activity is an overview, not the full event log. Keep the most
            # recent event for each task; the task detail view still exposes
            # the complete history.
            latest_by_task.setdefault(event.task_id, event)
        for event in latest_by_task.values():
            kind = status_label(event.kind)
            task = self.mission_store.get_task(event.task_id)
            task_label = task.title if task is not None else tr("task {id}", id=event.task_id[:8])
            item = QListWidgetItem(f"{kind}  ·  {task_label}\n{tr(event.message)}  ·  {event.created_at}")
            item.setData(Qt.ItemDataRole.UserRole, event.task_id)
            item.setSizeHint(QSize(0, 46))
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
            summary = tr(
                "Approval\nAction: {action}\nTask: {task}\nStatus: {status}",
                action=approval.action, task=approval.task_id, status=status_label(approval.status),
            )
            self.mission_details.setPlainText(
                f"{summary}\n\n{json.dumps(approval.payload, ensure_ascii=False, indent=2)}"
            )

    def refresh_mission_workflows(self) -> None:
        self.mission_workflows.clear()
        for workflow in self.mission_store.list_workflows():
            item = QListWidgetItem(f"{workflow.name}\n" + tr("{count} steps  ·  multi-agent pipeline", count=len(workflow.steps)))
            item.setData(Qt.ItemDataRole.UserRole, workflow.id)
            item.setSizeHint(QSize(0, 58))
            item.setToolTip("\n".join(f"{step.name} → {step.agent_id or 'Arqen'}" for step in workflow.steps))
            self.mission_workflows.addItem(item)

    def refresh_mission_workflow_runs(self) -> None:
        selected_id = None
        if hasattr(self, "mission_workflow_runs") and self.mission_workflow_runs.currentItem() is not None:
            selected_id = self.mission_workflow_runs.currentItem().data(Qt.ItemDataRole.UserRole)
        self.mission_workflow_runs.clear()
        for run in self.mission_store.list_workflow_runs():
            heading = tr("{status}  ·  step {step}", status=status_label(run.status), step=run.current_step)
            item = QListWidgetItem(f"{heading}\n{run.workflow_id}  ·  {run.id[:8]}")
            item.setData(Qt.ItemDataRole.UserRole, run.id)
            item.setSizeHint(QSize(0, 52))
            item.setToolTip("\n".join(run.results) or tr("No results yet"))
            self.mission_workflow_runs.addItem(item)
            if run.id == selected_id:
                self.mission_workflow_runs.setCurrentItem(item)
        if selected_id and self.mission_workflow_runs.currentItem() is not None:
            self._show_workflow_run(self.mission_workflow_runs.currentItem())

    def _create_mission_workflow(self) -> None:
        name, accepted = QInputDialog.getText(self, tr("New workflow"), tr("Name:"))
        if not accepted or not name.strip():
            return
        raw, accepted = QInputDialog.getMultiLineText(self, tr("New workflow"), tr("One step per line: name | prompt | agent-id (optional)"))
        if not accepted:
            return
        steps = []
        for line in raw.splitlines():
            parts = [part.strip() for part in line.split("|", 2)]
            if len(parts) >= 2 and parts[0] and parts[1]:
                steps.append(WorkflowStep(parts[0], parts[1], parts[2] if len(parts) == 3 and parts[2] else None))
        if not steps:
            QMessageBox.warning(self, tr("Mission Control"),tr("At least one valid step is required."))
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
        topic, accepted = QInputDialog.getText(self, tr("Run workflow"), tr("Topic:"))
        if not accepted or not topic.strip():
            return
        audience, accepted = QInputDialog.getText(self, tr("Run workflow"), tr("Target audience (optional):"))
        if not accepted:
            return
        content_format, accepted = QInputDialog.getText(self, tr("Run workflow"), tr("Content format (optional):"), text=tr("YouTube video"))
        if not accepted:
            return
        input_text = f"Ämne: {topic.strip()}"
        if audience.strip():
            input_text += f"\nMålgrupp: {audience.strip()}"
        if content_format.strip():
            input_text += f"\nFormat: {content_format.strip()}"
        try:
            self.workflow_runner.run(workflow.name, list(workflow.steps), workflow_id=workflow.id, input_text=input_text)
        except Exception as exc:
            QMessageBox.warning(self, tr("Mission Control"),str(exc))
        self.refresh_mission_tasks()
        self.refresh_mission_workflow_runs()
        self.refresh_mission_approvals()
        self.refresh_mission_activity()
        self.refresh_dashboard()

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
            QMessageBox.warning(self, tr("Mission Control"),str(exc))
        self.refresh_mission_tasks()
        self.refresh_mission_workflow_runs()

    def refresh_mission_schedules(self) -> None:
        self.mission_schedules.clear()
        for schedule in self.mission_store.list_schedules():
            mode = self._schedule_display(schedule)
            state = tr("ON") if schedule.enabled else tr("OFF")
            agent = self.mission_store.get_agent(schedule.agent_id) if schedule.agent_id else None
            workflow = next((item for item in self.mission_store.list_workflows() if item.id == schedule.workflow_id), None) if schedule.workflow_id else None
            count = sum(1 for task in self.mission_store.list_tasks() if task.schedule_id == schedule.id)
            last = schedule.last_run_at or "aldrig"
            target = tr("workflow: {name}", name=workflow.name) if workflow else tr("task: {name}", name=agent.name if agent else "Arqen")
            counts = tr("{count} tasks", count=count)
            item = QListWidgetItem(f"{schedule.name}\n{state}  ·  {mode}\n{target}  ·  {counts}  ·  {tr('last: {last}', last=last)}")
            item.setData(Qt.ItemDataRole.UserRole, schedule.id)
            item.setSizeHint(QSize(0, 72))
            item.setToolTip(tr("Last run: {last}", last=last))
            item.setForeground(QColor("#b7ff18" if schedule.enabled else "#657078"))
            self.mission_schedules.addItem(item)

    @staticmethod
    def _schedule_display(schedule: Schedule) -> str:
        if not schedule.cron:
            return tr("One time: {when}", when=schedule.run_at or tr("not set"))
        parts = schedule.cron.split()
        if len(parts) != 5:
            return tr("Advanced: {cron}", cron=schedule.cron)
        minute, hour, day, month, weekday = parts
        try:
            time_label = f"{int(hour):02d}:{int(minute):02d}"
        except ValueError:
            return tr("Advanced: {cron}", cron=schedule.cron)
        if day == "*" and month == "*" and weekday == "*":
            return tr("Every day at {time}", time=time_label)
        if day == "*" and month == "*" and weekday != "*":
            names = {"0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday", "7": "Sunday"}
            return tr("Every {day} at {time}", day=tr(names.get(weekday, weekday)), time=time_label)
        if day != "*" and month == "*" and weekday == "*":
            return tr("Monthly on day {day} at {time}", day=day, time=time_label)
        return tr("Advanced: {cron}", cron=schedule.cron)

    def _create_mission_schedule(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("New schedule"))
        dialog_layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name = QLineEdit()
        name.setPlaceholderText(tr("e.g. Morning research"))
        form.addRow(tr("Name"), name)
        prompt = QTextEdit()
        prompt.setPlaceholderText(tr("Describe what should happen when this schedule runs."))
        prompt.setMinimumHeight(90)
        form.addRow(tr("Instruction"), prompt)
        run = QComboBox()
        run.addItem(tr("A regular task"), None)
        workflows = self.mission_store.list_workflows()
        for workflow in workflows:
            run.addItem(tr("Workflow: {name}", name=workflow.name), workflow.id)
        form.addRow(tr("Run"), run)
        agents = [agent for agent in self.mission_store.list_agents() if agent.enabled]
        agent_box = QComboBox()
        agent_box.addItem(tr("Arqen default"), None)
        for agent in agents:
            agent_box.addItem(f"{agent.name} — {agent.role}", agent.id)
        form.addRow(tr("Agent"), agent_box)
        frequency = QComboBox()
        # The visible text is translated; the English value drives the logic below.
        for mode_name in ("Every day", "Every week", "Every month", "One time", "Advanced (cron)"):
            frequency.addItem(tr(mode_name), mode_name)
        form.addRow(tr("When"), frequency)
        weekday = QComboBox()
        weekday.addItems([tr(day).capitalize() for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")])
        form.addRow(tr("Weekday"), weekday)
        timing = QLineEdit("08:00")
        timing.setPlaceholderText("HH:MM")
        form.addRow(tr("Time"), timing)
        help_label = QLabel(tr("Choose a simple schedule. Advanced cron is optional."))
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #8d969d; font-size: 11px;")
        dialog_layout.addLayout(form)
        dialog_layout.addWidget(help_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        def update_schedule_fields() -> None:
            value = frequency.currentData()
            timing.setPlaceholderText("ISO-8601 UTC" if value == "One time" else "HH:MM")
            weekday.setEnabled(value == "Every week")
            weekday.setToolTip(tr("Used only for weekly schedules."))

        frequency.currentIndexChanged.connect(lambda _: update_schedule_fields())
        update_schedule_fields()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not name.text().strip() or not prompt.toPlainText().strip():
            QMessageBox.warning(self, tr("New schedule"), tr("Fill in both a name and an instruction."))
            return
        mode = frequency.currentData()
        value = timing.text().strip()
        if mode == "One time":
            if re.fullmatch(r"\d{1,2}:\d{2}", value):
                hour, minute = (int(part) for part in value.split(":"))
                local_now = datetime.now().astimezone()
                local_target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                value = local_target.astimezone(timezone.utc).isoformat()
            else:
                try:
                    datetime.fromisoformat(value)
                except ValueError:
                    QMessageBox.warning(self, tr("New schedule"), tr("Use HH:MM or an ISO-8601 date and time."))
                    return
            schedule = Schedule(uuid4().hex, name.text().strip(), prompt.toPlainText().strip(), run_at=value)
        elif mode == "Advanced (cron)":
            schedule = Schedule(uuid4().hex, name.text().strip(), prompt.toPlainText().strip(), cron=value)
        else:
            if not re.fullmatch(r"\d{1,2}:\d{2}", value):
                QMessageBox.warning(self, tr("New schedule"), tr("Time must use HH:MM, for example 08:00."))
                return
            hour, minute = value.split(":")
            cron = f"{int(minute)} {int(hour)} * * *"
            if mode == "Every week":
                cron = f"{int(minute)} {int(hour)} * * {weekday.currentIndex() + 1 if weekday.currentIndex() < 6 else 0}"
            elif mode == "Every month":
                cron = f"{int(minute)} {int(hour)} 1 * *"
            schedule = Schedule(uuid4().hex, name.text().strip(), prompt.toPlainText().strip(), cron=cron)
        schedule = Schedule(schedule.id, schedule.name, schedule.prompt, agent_box.currentData(), schedule.cron, schedule.run_at, True, schedule.created_at, None, run.currentData())
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

    def _delete_mission_schedule(self) -> None:
        item = self.mission_schedules.currentItem()
        if item is None:
            return
        schedule_id = item.data(Qt.ItemDataRole.UserRole)
        schedule = next((entry for entry in self.mission_store.list_schedules() if entry.id == schedule_id), None)
        if schedule is None:
            return
        answer = QMessageBox.question(
            self,
            tr("Delete schedule"),
            tr("Delete '{name}'? Existing tasks will be kept.", name=schedule.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.mission_store.delete_schedule(schedule.id)
        self.refresh_mission_schedules()

    def refresh_mission_agents(self) -> None:
        for group_list in self.agent_group_lists.values():
            group_list.clear()
        while self.nexus_card_layout.count():
            child = self.nexus_card_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        agents = self.mission_store.list_agents()
        agents.sort(key=lambda agent: agent.name.lower())
        for agent in agents:
            status = self.mission_runner.runtime_status(agent.id)
            tools = ", ".join(agent.allowed_tools) or tr("no tools")
            approvals = ", ".join(agent.approval_tools) or tr("none")
            card = QFrame(objectName="panel")
            card.setFixedSize(270, 154)
            card.setStyleSheet(
                "QFrame#panel { background: #171d21; border: 1px solid #30383a; border-radius: 8px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(5)
            heading = QHBoxLayout()
            indicator = QLabel("●")
            indicator_color = "#b7ff18" if agent.enabled else "#657078"
            indicator.setStyleSheet(f"color: {indicator_color}; font-size: 14px;")
            heading.addWidget(indicator)
            heading.addWidget(QLabel(agent.name, objectName="title"))
            heading.addStretch(1)
            card_layout.addLayout(heading)
            role_label = QLabel(agent.role)
            role_label.setStyleSheet("color: #dbe2df; font-weight: 600;")
            card_layout.addWidget(role_label)
            runtime_label = QLabel(tr("{runtime} runtime  ·  {count} tools", runtime=agent.runtime, count=len(agent.allowed_tools)))
            runtime_label.setStyleSheet("color: #8d969d; font-size: 11px;")
            card_layout.addWidget(runtime_label)
            state_label = QLabel(tr("ENABLED") if agent.enabled else tr("DISABLED"))
            state_label.setStyleSheet(f"color: {indicator_color}; font-size: 10px; letter-spacing: 1px;")
            card_layout.addWidget(state_label)
            chat = QPushButton(tr("CHAT"))
            self._style_page_action(chat)
            chat.clicked.connect(lambda _, name=agent.name: self._open_agent_chat(name))
            card_layout.addWidget(chat)
            card.setToolTip(tr(
                "{detail}\nAllowed tools: {tools}\nRequires approval: {approvals}",
                detail=status.get("detail", status.get("status", "")), tools=tools, approvals=approvals,
            ))
            if agent.id == "nexus":
                self.nexus_card_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
            else:
                if agent.id in {"scout", "archivist"}:
                    group_list = self.agent_group_lists["RESEARCH"]
                elif agent.id in {"forge", "pixel", "pilot"}:
                    group_list = self.agent_group_lists["PRODUCTION"]
                else:
                    group_list = self.agent_group_lists["DISTRIBUTION & REVIEW"]
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, agent.id)
                group_list.addItem(item)
                group_list.setItemWidget(item, card)
                item.setSizeHint(card.sizeHint())

    def _open_agent_chat(self, agent_name: str) -> None:
        self._select_navigation("Chat")
        self.set_status(self.provider_status(tr("CHAT // {name}", name=agent_name.upper())))

    def _create_mission_agent(self) -> None:
        agent_id, accepted = QInputDialog.getText(self, tr("New agent"), "ID:")
        if not accepted or not agent_id.strip():
            return
        name, accepted = QInputDialog.getText(self, tr("New agent"), tr("Name:"))
        if not accepted or not name.strip():
            return
        role, accepted = QInputDialog.getText(self, tr("New agent"), tr("Role:"))
        if not accepted or not role.strip():
            return
        runtime, accepted = QInputDialog.getItem(self, tr("New agent"), tr("Runtime:"), ["arqen", "hermes"], 0, False)
        if not accepted:
            return
        available = [item["name"] for item in self.engine.tools.describe()]
        tools_dialog = QDialog(self)
        tools_dialog.setWindowTitle(tr("New agent — Allowed tools"))
        tools_layout = QVBoxLayout(tools_dialog)
        tools_layout.addWidget(QLabel(tr("Select tools by entering their names, separated by commas.")))
        available_view = QTextEdit(readOnly=True)
        available_view.setPlainText("\n".join(available))
        available_view.setMaximumHeight(150)
        tools_layout.addWidget(available_view)
        tools_layout.addWidget(QLabel(tr("Allowed tools")))
        tools_input = QLineEdit()
        tools_input.setPlaceholderText(tr("e.g. system_status,current_time"))
        tools_layout.addWidget(tools_input)
        tool_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        tool_buttons.accepted.connect(tools_dialog.accept)
        tool_buttons.rejected.connect(tools_dialog.reject)
        tools_layout.addWidget(tool_buttons)
        if tools_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        tools_text = tools_input.text()
        allowed_tools = tuple(item.strip() for item in tools_text.split(",") if item.strip())
        unknown = sorted(set(allowed_tools) - set(available))
        if unknown:
            QMessageBox.warning(self, tr("Mission Control"),tr("Unknown tools: {tools}", tools=", ".join(unknown)))
            return
        approvals_text, accepted = QInputDialog.getText(self, tr("New agent"), tr("Tools requiring approval (comma-separated):"))
        if not accepted:
            return
        approval_tools = tuple(value.strip() for value in approvals_text.split(",") if value.strip())
        invalid_approvals = sorted(set(approval_tools) - set(allowed_tools))
        if invalid_approvals:
            QMessageBox.warning(self, tr("Mission Control"),tr("Approval tools must be included in the allowlist."))
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
        # replace() keeps the tools and approval rules; building a new Agent here
        # used to drop them, so toggling emptied the agent's allowance.
        self.mission_store.save_agent(replace_dataclass(agent, enabled=not agent.enabled))
        self.refresh_mission_agents()

    def _edit_mission_agent(self) -> None:
        item = self.mission_agents.currentItem()
        if item is None:
            return
        agent = self.mission_store.get_agent(item.data(Qt.ItemDataRole.UserRole))
        if agent is None:
            return
        name, accepted = QInputDialog.getText(self, tr("Edit agent"), tr("Name:"), text=agent.name)
        if not accepted or not name.strip():
            return
        role, accepted = QInputDialog.getText(self, tr("Edit agent"), tr("Role:"), text=agent.role)
        if not accepted or not role.strip():
            return
        runtime, accepted = QInputDialog.getItem(self, tr("Edit agent"), tr("Runtime:"), ["arqen", "hermes"], max(0, ["arqen", "hermes"].index(agent.runtime)), False)
        if not accepted:
            return
        current_tools = ", ".join(agent.allowed_tools)
        tools_text, accepted = QInputDialog.getText(self, tr("Edit agent"), tr("Allowed tools:"), text=current_tools)
        if not accepted:
            return
        available = {entry["name"] for entry in self.engine.tools.describe()}
        allowed_tools = tuple(value.strip() for value in tools_text.split(",") if value.strip())
        unknown = sorted(set(allowed_tools) - available)
        if unknown:
            QMessageBox.warning(self, tr("Mission Control"),tr("Unknown tools: {tools}", tools=", ".join(unknown)))
            return
        approvals_text, accepted = QInputDialog.getText(self, tr("Edit agent"), tr("Tools requiring approval:"), text=", ".join(agent.approval_tools))
        if not accepted:
            return
        approval_tools = tuple(value.strip() for value in approvals_text.split(",") if value.strip())
        if set(approval_tools) - set(allowed_tools):
            QMessageBox.warning(self, tr("Mission Control"),tr("Approval tools must be included in the allowlist."))
            return
        self.mission_store.save_agent(Agent(agent.id, name.strip(), role.strip(), runtime, agent.enabled, allowed_tools, approval_tools))
        self.refresh_mission_agents()

    def refresh_mission_tasks(self) -> None:
        if not hasattr(self, "mission_tasks"):
            return
        selected_id = None
        if self.mission_tasks.currentItem() is not None:
            selected_id = self.mission_tasks.currentItem().data(Qt.ItemDataRole.UserRole)
        self.mission_tasks.clear()
        tasks = self.mission_store.list_tasks()
        if getattr(self, "tasks_attention_only", False):
            tasks = [task for task in tasks if task.status in {"failed", "cancelled"}]
        for task in tasks:
            agent = self.mission_store.get_agent(task.agent_id) if task.agent_id else None
            agent_label = agent.name if agent else tr("Arqen default")
            status = status_label(task.status)
            item = QListWidgetItem(f"{task.title}\n{status}  ·  {agent_label}")
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setSizeHint(QSize(0, 64))
            item.setToolTip(task.prompt)
            if task.status in {"failed", "cancelled"}:
                item.setForeground(QColor("#ff6b6b"))
            elif task.status in {"waiting_approval", "queued"}:
                item.setForeground(QColor("#ffd166"))
            elif task.status == "completed":
                item.setForeground(QColor("#b7ff18"))
            self.mission_tasks.addItem(item)
            if task.id == selected_id:
                self.mission_tasks.setCurrentItem(item)
        if selected_id:
            self._show_mission_task()

    def _set_task_filter(self, attention_only: bool) -> None:
        self.tasks_attention_only = attention_only
        self.refresh_mission_tasks()

    def _open_attention_tasks(self) -> None:
        self.tasks_attention_only = True
        self._select_navigation("Tasks")
        self.refresh_mission_tasks()

    def _open_pending_approvals(self) -> None:
        # The approvals list lives on the Tasks page.
        self._select_navigation("Tasks")
        if hasattr(self, "mission_approvals") and self.mission_approvals.count():
            item = self.mission_approvals.item(0)
            self.mission_approvals.setCurrentItem(item)
            self.mission_approvals.scrollToItem(item)
            self._show_selected_approval(item)

    def refresh_mission_approvals(self) -> None:
        self.mission_approvals.clear()
        for approval in self.mission_store.list_approvals("pending"):
            item = QListWidgetItem(f"{approval.action} [{approval.task_id[:8]}]")
            item.setData(Qt.ItemDataRole.UserRole, approval.id)
            self.mission_approvals.addItem(item)

    def _decide_mission_approval(self, status: str, approval_id: str | None = None) -> None:
        if approval_id is None:
            item = self.mission_approvals.currentItem()
            if item is None:
                return
            approval_id = item.data(Qt.ItemDataRole.UserRole)
        self.mission_store.decide_approval(approval_id, status)
        approval = self.mission_store.get_approval(approval_id)
        # Resume on both answers: a rejection is what moves the task to
        # cancelled, otherwise it waits for approval forever.
        if approval is not None:
            try:
                self.mission_runner.resume(approval.task_id)
            except Exception as exc:
                QMessageBox.warning(self, tr("Mission Control"),str(exc))
        self.refresh_mission_tasks()
        self.refresh_mission_agents()
        self.refresh_mission_approvals()
        self._refresh_approval_bar()
        self._show_mission_task()

    def _selected_mission_task(self) -> Task | None:
        item = self.mission_tasks.currentItem()
        return self.mission_store.get_task(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _show_mission_task(self) -> None:
        task = self._selected_mission_task()
        if task is None:
            return
        self.mission_result_button.setEnabled(bool(task.result))
        events = self.mission_store.list_events(task.id)
        agent = self.mission_store.get_agent(task.agent_id) if task.agent_id else None
        agent_label = agent.name if agent else tr("Arqen default")
        source = task.schedule_id or tr("manual")
        if task.result:
            result = clean_result_markup(task.result)
        else:
            result = tr("No result stored.") if task.status == "completed" else tr("Not available yet.")
        lines = [
            task.title,
            "",
            f"{tr('STATUS'):<11}{status_label(task.status)}",
            f"{tr('AGENT'):<11}{agent_label}",
            f"{tr('SOURCE'):<11}{source}",
            f"{tr('ATTEMPTS'):<11}{task.attempts}/{task.max_attempts}",
            f"{tr('ERROR'):<11}{tr(task.error) if task.error else tr('none')}",
            "",
            tr("INSTRUCTION"),
            task.prompt,
            "",
            tr("RESULT"),
            result,
            "",
            tr("EVENT HISTORY"),
        ]
        lines.extend(f"{event.created_at}  {status_label(event.kind)}: {tr(event.message)}" for event in events)
        self.mission_details.setPlainText("\n".join(lines))

    def _open_selected_task_result(self) -> None:
        task = self._selected_mission_task()
        if task is None or not task.result:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Result — {title}", title=task.title))
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        result = QTextEdit(readOnly=True)
        result.setMarkdown(clean_result_markup(task.result))
        layout.addWidget(result)
        close = QPushButton(tr("CLOSE"))
        self._style_page_action(close, primary=True)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignLeft)
        dialog.exec()

    def _create_mission_task(self) -> None:
        title, accepted = QInputDialog.getText(self, tr("New Mission Control task"), tr("Title:"))
        if not accepted or not title.strip():
            return
        prompt, accepted = QInputDialog.getMultiLineText(self, tr("New Mission Control task"), tr("Task:"))
        if not accepted or not prompt.strip():
            return
        agents = self.mission_store.list_agents()
        agent_id = None
        if agents:
            labels = [tr("No agent (Arqen default)")] + [f"{agent.name} — {agent.role}" for agent in agents if agent.enabled]
            selected, accepted = QInputDialog.getItem(self, "Tilldela agent", tr("Agent:"), labels, 0, False)
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
        self.mission_details.setPlainText(tr("{title}\nStatus: RUNNING\n\nArqen is working...", title=task.title))
        self.mission_thread.start()

    def _delete_queued_task(self) -> None:
        task = self._selected_mission_task()
        if task is None or task.status == "waiting_approval":
            QMessageBox.information(self, tr("Delete task"), tr("Tasks waiting for approval cannot be deleted."))
            return
        warning = tr("The active model call may take a short moment to stop.") if task.status == "running" else tr("This removes it from Mission Control.")
        answer = QMessageBox.question(
            self,
            tr("Delete task"),
            tr("Delete '{title}'?\n\n{warning}", title=task.title, warning=warning),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.mission_store.delete_task(task.id)
        self.refresh_mission_tasks()
        self.refresh_dashboard()

    def _retry_mission_task(self) -> None:
        task = self._selected_mission_task()
        if task is None or task.status != "failed":
            return
        if not self.mission_store.retry_task(task.id):
            QMessageBox.information(self, tr("Mission Control"),tr("The task has reached its maximum attempts."))
            return
        self.refresh_mission_tasks()
        self._show_mission_task()

    def _mission_finished(self, result: str) -> None:
        self.refresh_mission_tasks()
        self.refresh_mission_agents()
        self._show_mission_task()

    def _mission_failed(self, message: str) -> None:
        QMessageBox.warning(self, tr("Mission Control"),message)
        self.refresh_mission_tasks()
        self._show_mission_task()

    def _mission_thread_finished(self) -> None:
        self.mission_tasks.setEnabled(True)
        self.mission_thread = None
        self.mission_worker = None

    def _build_chat_list(self) -> QFrame:
        panel = QFrame(objectName="chatListPanel")
        panel.setFixedWidth(250)
        panel.setStyleSheet(
            "QFrame#chatListPanel { background: #111516; border: 1px solid #252d30; border-radius: 8px; }"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 12, 10, 10)
        panel_layout.setSpacing(8)
        panel_layout.addWidget(QLabel(tr("CHATS"), objectName="sectionLabel"))
        new_chat = QPushButton(tr("NEW CHAT"))
        self._style_page_action(new_chat, primary=True)
        new_chat.clicked.connect(self.create_new_session)
        panel_layout.addWidget(new_chat)
        self.chat_list = QListWidget()
        self.chat_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.chat_list.setUniformItemSizes(True)
        self.chat_list.setToolTip(tr("Right-click to open, rename or delete. F2 renames, Delete removes."))
        self.chat_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { color: #c4cec9; padding: 7px 8px; border-radius: 5px; border-left: 2px solid transparent; }"
            "QListWidget::item:hover { background: #1b2226; color: #f2f0eb; }"
            "QListWidget::item:selected { background: #1f2a20; color: #f2f0eb; border-left: 2px solid #b7ff18; }"
        )
        self.chat_list.itemClicked.connect(lambda _: self.load_selected_session())
        self.chat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self.show_session_menu)
        self.chat_list.installEventFilter(self)
        panel_layout.addWidget(self.chat_list, 1)
        return panel

    def show_session_menu(self, position) -> None:
        item = self.chat_list.itemAt(position)
        if item is None:
            return
        self.chat_list.setCurrentItem(item)
        menu = QMenu(self)
        open_action = menu.addAction(tr("Open"))
        rename_action = menu.addAction(tr("Rename"))
        delete_action = menu.addAction(tr("Delete"))
        selected = menu.exec(self.chat_list.viewport().mapToGlobal(position))
        if selected == open_action:
            self.load_selected_session()
        elif selected == rename_action:
            self.rename_selected_session()
        elif selected == delete_action:
            self.delete_selected_session()

    def _create_visualization_dock(self) -> None:
        self.visualization_dock = QDockWidget(tr("ARQEN VOICE"), self)
        self.visualization_dock.setObjectName("voiceVisualizationDock")
        self.visualization_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.visualization_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        palette = self.voice_palette = load_voice_palette()
        self.voice_panel = VoiceVisualizationWidget(palette)
        container = QWidget()
        container.setStyleSheet(f"background: {palette.background};")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 12)
        container_layout.setSpacing(4)
        container_layout.addWidget(self.voice_panel, 1)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        for button in (self.mic_button, self.voice_button):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(96)
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {palette.muted}; border: 1px solid {palette.structure}; "
                "border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: bold; letter-spacing: 1px; }"
                f"QPushButton:hover {{ color: {palette.text}; border-color: {palette.muted}; }}"
                f"QPushButton:checked {{ color: {palette.accent}; border-color: {palette.accent}; }}"
            )
            controls.addWidget(button)
        controls.addStretch(1)
        container_layout.addLayout(controls)
        self.visualization_dock.setWidget(container)
        self._sync_voice_controls()
        set_audio_level_callback(self.voice_panel.set_audio_level)
        self.microphone.on_level = self.voice_panel.set_input_level
        self.voice_panel.set_model_label(getattr(self.engine.provider, "model", "") or self.provider_label)
        # Voice and stats share a column on the right; either can still be
        # undocked, and then opens where it was last left floating.
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.visualization_dock)
        self.visualization_dock.setMinimumSize(240, 310)
        self.visualization_dock.installEventFilter(self)
        self.visualization_dock.topLevelChanged.connect(
            lambda floating: floating and self._apply_placement("voice_visualization", self.visualization_dock, 240, 270)
        )

    def _create_stats_dock(self) -> None:
        self.stats_dock = QDockWidget(tr("ARQEN STATS"), self)
        self.stats_dock.setObjectName("statsDock")
        self.stats_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.stats_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.stats_panel = StatsPanelWidget(self.voice_palette)
        self.stats_dock.setWidget(self.stats_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.stats_dock)
        self.splitDockWidget(self.visualization_dock, self.stats_dock, Qt.Orientation.Vertical)
        self.stats_dock.setMinimumSize(240, 200)
        self.stats_dock.installEventFilter(self)
        self.stats_dock.topLevelChanged.connect(
            lambda floating: floating and self._apply_placement("stats_panel", self.stats_dock, 240, 200)
        )
        # Dock sizes only stick once the window has its real geometry.
        QTimer.singleShot(0, self._size_right_docks)

    def _size_right_docks(self) -> None:
        self.resizeDocks([self.visualization_dock], [290], Qt.Orientation.Horizontal)
        self.resizeDocks([self.visualization_dock, self.stats_dock], [340, 300], Qt.Orientation.Vertical)
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
        if hasattr(self, "scheduler_worker"):
            self.scheduler_worker.stop()
        if hasattr(self, "task_worker"):
            self.task_worker.stop()
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
        if watched is getattr(self, "chat_list", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_F2:
                self.rename_selected_session()
                return True
            if event.key() == Qt.Key.Key_Delete:
                self.delete_selected_session()
                return True
        if event.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
            for attribute, key in self._DOCK_GEOMETRY_KEYS.items():
                dock = getattr(self, attribute, None)
                if watched is dock and dock.isFloating():
                    self._store_placement(key, dock)
                    break
        return super().eventFilter(watched, event)

    def send_message(self) -> None:
        if getattr(self, "_voice_pending_send", False):
            self._voice_pending_send = False
            self._refresh_voice_state()
        prompt = self.input.text().strip()
        if not prompt:
            return
        self.append_message(tr("YOU"), prompt, CyberpunkGreenTheme.accent)
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
        self._voice_thinking = True
        self._voice_pending_send = False
        self._refresh_voice_state()
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

    def provider_status(self, state: str | None = None, elapsed_ms: float | None = None) -> str:
        state = tr("READY") if state is None else state
        provider = getattr(self.engine.provider, "provider_name", self.provider_label)
        model = getattr(self.engine.provider, "model", "")
        profile = tr({"private": "LOCAL - OLLAMA", "fast": "FAST", "important": "IMPORTANT", "creative": "CREATIVE"}.get(
            self.profile_name,
            {"local": "PRIVATE", "openrouter": "FAST", "openai": "IMPORTANT"}.get(provider.lower(), "CUSTOM"),
        ))
        heading = f"{tr('PROFILE')}: {profile} // {provider.upper()}"
        details = f"{heading} / {model}" if model else heading
        if getattr(self.engine.provider, "fallback_used", False):
            details = f"{tr('FALLBACK')} // {details}"
            reason = getattr(self.engine.provider, "fallback_reason", "")
            if reason:
                details += f" // {reason}"
        suffix = f" // {elapsed_ms / 1000:.1f}s" if elapsed_ms is not None else ""
        return f"{state} // {details}{suffix}"

    def set_status(self, text: str) -> None:
        upper = text.upper()
        words = set(re.findall(r"[A-ZÅÄÖ]+", upper))
        color = CyberpunkGreenTheme.muted
        # Both languages are checked: provider and microphone code reports in English.
        if words & {"ERROR", "FEL"}:
            color = CyberpunkGreenTheme.danger
        elif words & {"FALLBACK", "RESERV"}:
            color = "#ffad4d"
        elif any(name in upper for name in ("OPENAI", "OPENROUTER", "GEMINI", "CLAUDE")):
            color = "#75bfff"
        elif words & {"READY", "REDO", "LOCAL", "LOKAL"}:
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
        self._set_voice_button_text("🔊" if self.engine.voice_enabled else "🔇")
        if self.engine.last_response_speakable:
            from arqen.tools.speech import SpeakTextTool
            self.stop_button.setEnabled(True)
            threading.Thread(
                target=lambda: SpeakTextTool().run({"text": result}),
                daemon=True,
                name="arqen-auto-speech",
            ).start()
            QTimer.singleShot(250, self._refresh_speech_stop_state)
        self.set_status(self.provider_status(tr("READY // RESPONSE COMPLETE"), elapsed_ms))
        self.refresh_stats_panel()
        self.refresh_sessions()

    def _set_voice_button_text(self, text: str) -> None:
        """Kept for existing callers; the controls now derive their own label."""
        self._sync_voice_controls()

    def _sync_voice_controls(self) -> None:
        """Show the real microphone and voice state on the voice panel's toggles."""
        try:
            recording = self.microphone.recording
            self.mic_button.setChecked(recording)
            self.mic_button.setText(tr("● REC") if recording else tr("🎙 MIC"))
            self.mic_button.setToolTip(tr("Stop microphone recording") if recording else tr("Start microphone recording"))
            voice_on = bool(self.engine.voice_enabled)
            self.voice_button.setChecked(voice_on)
            self.voice_button.setText(tr("🔊 VOICE") if voice_on else tr("🔇 VOICE"))
            self.voice_button.setToolTip(tr("Turn spoken replies off") if voice_on else tr("Turn spoken replies on"))
        except (AttributeError, RuntimeError):
            # A response can finish after Qt has deleted the controls.
            return

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
        self.append_message(tr("ERROR"), message, CyberpunkGreenTheme.danger)
        self.refresh_stats_panel()
        self.set_status(self.provider_status(tr("ERROR // REQUEST FAILED")))

    def response_cancelled(self) -> None:
        self._loading_timer.stop()
        self.set_status(self.provider_status(tr("STOPPED // RESPONSE DISCARDED")))

    def _animate_loading(self) -> None:
        self._loading_phase = (self._loading_phase + 1) % 4
        dots = "." * self._loading_phase
        self.set_status(self.provider_status(tr("WORKING // PROCESSING REQUEST") + dots))

    def response_thread_finished(self) -> None:
        self.worker.deleteLater()
        self.thread.deleteLater()
        self._voice_thinking = False
        self._refresh_voice_state()
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
            self.set_status(self.provider_status(tr("STOPPED // RESPONSE DISCARDED") if running else tr("READY")))
            self.stop_button.setEnabled(False)
        except RuntimeError:
            # The response thread may already have been deleted by Qt.
            return

    def toggle_voice_mode(self) -> None:
        self.engine.voice_enabled = not self.engine.voice_enabled
        if self.engine.voice_enabled:
            self._set_voice_button_text("🔊")
            self.set_status(self.provider_status(tr("VOICE // ENABLED")))
        else:
            try:
                from arqen.tools.speech import stop_speech
                stop_speech()
            except Exception:
                pass
            self._set_voice_button_text("🔇")
            self.set_status(self.provider_status(tr("VOICE // DISABLED")))

    _MIC_BUSY_STATUSES = ("STOPPING", "LOADING MODEL", "DECODING")

    @pyqtSlot(str)
    def _on_microphone_status(self, status: str) -> None:
        self._voice_transcribing = any(busy in status for busy in self._MIC_BUSY_STATUSES)
        self._refresh_voice_state()

    def _refresh_voice_state(self) -> None:
        """Pick the voice ring's base state; speaking is detected by the ring itself."""
        panel = getattr(self, "voice_panel", None)
        if panel is None:
            return
        if self.microphone.recording:
            state = "listening"
        elif (
            getattr(self, "_voice_thinking", False)
            or getattr(self, "_voice_transcribing", False)
            or getattr(self, "_voice_pending_send", False)
        ):
            state = "thinking"
        else:
            state = "idle"
        panel.set_state(state)

    def toggle_microphone(self) -> None:
        if self.microphone.recording:
            self.microphone.stop()
        else:
            self.microphone.start()
        self._sync_voice_controls()

    @pyqtSlot(str)
    def _handle_microphone_result(self, text: str) -> None:
        """Put a transcription in the composer and submit it automatically."""
        cleaned = text.strip()
        if not cleaned:
            return
        # Bridges the gap until send_message starts, so the ring does not
        # blink back to idle between transcription and the response.
        self._voice_pending_send = True
        self._refresh_voice_state()
        self.input.setText(cleaned)
        QTimer.singleShot(100, self.send_message)

    def show_tool_request(self, name: str) -> None:
        self.set_status(tr("TOOL // {name}", name=name.upper()))
        self._end_streaming_block()
        self.append_message(tr("TOOL"), name, CyberpunkGreenTheme.muted)

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
        chat_list = getattr(self, "chat_list", None)
        if chat_list is None:
            return
        try:
            chat_list.blockSignals(True)
            chat_list.clear()
            current_id = self.engine.session.session_id if self.engine.session else None
            for session in self.engine.session_store.list_sessions():
                # Multi-line titles (task instructions) would break the row height.
                title = " ".join(session.title.split()) or tr("New chat")
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, session.session_id)
                item.setToolTip(title)
                chat_list.addItem(item)
                if session.session_id == current_id:
                    chat_list.setCurrentItem(item)
            chat_list.blockSignals(False)
        except RuntimeError:
            # A late response callback may run after Qt has deleted the chat UI.
            return

    def create_new_session(self) -> None:
        title, accepted = QInputDialog.getText(self, tr("New chat"), tr("Title:"))
        if not accepted:
            return
        self.engine.new_session(title.strip() or tr("New chat"))
        self.output.clear()
        self.set_status(tr("READY // NEW SESSION"))
        self.refresh_sessions()

    def load_selected_session(self) -> None:
        selected = self.selected_session()
        if selected is None:
            return
        session = self.engine.load_session(selected.session_id)
        self.output.clear()
        for message in session.messages:
            if message.role == "user":
                self.append_message(tr("YOU"), message.content, CyberpunkGreenTheme.accent)
            elif message.role == "assistant":
                self.append_message("ARQEN", message.content, CyberpunkGreenTheme.text)
            elif message.role == "tool":
                self.append_message(tr("TOOL RESULT"), message.content, CyberpunkGreenTheme.muted)
                self.show_generated_image(message.content)
        self.set_status(tr("READY // SESSION LOADED"))

    def selected_session(self):
        """The chat picked in the chat list, looked up fresh from the store."""
        chat_list = getattr(self, "chat_list", None)
        item = chat_list.currentItem() if chat_list is not None else None
        session_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not session_id:
            return None
        matches = [s for s in self.engine.session_store.list_sessions() if s.session_id == session_id]
        return matches[0] if matches else None

    def rename_selected_session(self) -> None:
        session = self.selected_session()
        if session is None:
            return
        title, accepted = QInputDialog.getText(self, tr("Rename"), tr("New name:"), text=session.title)
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
            tr("Delete chat"),
            tr("Delete '{title}'?", title=session.title),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.engine.session_store.delete(session.session_id)
        if session.session_id == self.engine.session.session_id:
            self.engine.new_session()
            self.output.clear()
        self.refresh_sessions()

    def _build_approval_bar(self) -> QFrame:
        bar = QFrame(objectName="approvalBar")
        bar.setStyleSheet(
            "QFrame#approvalBar { background: #221f14; border: 1px solid #ffd166; border-radius: 8px; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 10, 8)
        row.setSpacing(10)
        heading = QLabel(tr("APPROVAL REQUIRED"))
        heading.setStyleSheet("color: #ffd166; font-weight: bold; font-size: 11px; letter-spacing: 1px;")
        row.addWidget(heading)
        self.approval_detail = QLabel()
        self.approval_detail.setStyleSheet("color: #f2f0eb; font-size: 12px;")
        self.approval_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.approval_detail, 1)
        self.approval_more = QPushButton()
        self.approval_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.approval_more.setStyleSheet(
            "QPushButton { background: transparent; color: #ffd166; border: none; padding: 4px 6px; }"
            "QPushButton:hover { text-decoration: underline; }"
        )
        self.approval_more.clicked.connect(self._open_pending_approvals)
        row.addWidget(self.approval_more)
        approve = QPushButton(tr("APPROVE"))
        reject = QPushButton(tr("REJECT"))
        self._style_page_action(approve, primary=True)
        self._style_page_action(reject)
        approve.clicked.connect(lambda: self._answer_first_approval(True))
        reject.clicked.connect(lambda: self._answer_first_approval(False))
        row.addWidget(approve)
        row.addWidget(reject)
        bar.hide()
        return bar

    def _pending_decisions(self) -> list[dict]:
        """Everything waiting on the user: the chat's tool first, then agent tasks."""
        decisions = []
        if self._chat_confirmation is not None:
            name, arguments = self._chat_confirmation
            decisions.append({"kind": "chat", "tool": name, "arguments": arguments, "source": tr("Arqen in chat")})
        store = getattr(self, "mission_store", None)
        if store is not None:
            for approval in store.list_approvals("pending"):
                task = store.get_task(approval.task_id)
                agent = store.get_agent(task.agent_id) if task is not None and task.agent_id else None
                source = task.title if task is not None else tr("task {id}", id=approval.task_id[:8])
                if agent is not None:
                    source = f"{agent.name}  ·  {source}"
                decisions.append({
                    "kind": "mission", "id": approval.id, "tool": approval.action,
                    "arguments": approval.payload.get("arguments", approval.payload) if isinstance(approval.payload, dict) else {},
                    "source": source,
                })
        return decisions

    @staticmethod
    def _describe_decision(decision: dict) -> str:
        title = tool_info(decision["tool"]).title
        values = [str(value) for value in (decision["arguments"] or {}).values() if str(value).strip()]
        detail = ", ".join(values)
        if len(detail) > 90:
            detail = detail[:87] + "..."
        parts = [title, detail, decision["source"]] if detail else [title, decision["source"]]
        return "  ·  ".join(parts)

    def _refresh_approval_bar(self) -> None:
        bar = getattr(self, "approval_bar", None)
        if bar is None:
            return
        decisions = self._pending_decisions()
        if not decisions:
            bar.hide()
            return
        self.approval_detail.setText(self._describe_decision(decisions[0]))
        self.approval_detail.setToolTip(self._describe_decision(decisions[0]))
        extra = len(decisions) - 1
        self.approval_more.setVisible(extra > 0)
        self.approval_more.setText(tr("+{count} more", count=extra))
        bar.show()

    def _answer_first_approval(self, accepted: bool) -> None:
        decisions = self._pending_decisions()
        if not decisions:
            self._refresh_approval_bar()
            return
        first = decisions[0]
        if first["kind"] == "chat":
            self.resolve_confirmation(accepted)
        else:
            self._decide_mission_approval("approved" if accepted else "rejected", approval_id=first["id"])

    def show_confirmation(self, name: str, arguments: dict | None = None) -> None:
        self.set_status(tr("CONFIRMATION REQUIRED // {name}", name=name.upper()))
        details = ""
        if arguments:
            details = " | " + ", ".join(
                f"{key}: {str(value)[:160]}" for key, value in arguments.items()
            )
        self._end_streaming_block()
        self.append_message(tr("CONFIRM"), f"{name}{details}", CyberpunkGreenTheme.accent)
        self._chat_confirmation = (name, dict(arguments or {}))
        self._refresh_approval_bar()
        self.confirm_button.setVisible(True)
        self.cancel_button.setVisible(True)
        self.confirm_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def resolve_confirmation(self, accepted: bool) -> None:
        self.confirm_button.setVisible(False)
        self.cancel_button.setVisible(False)
        self._chat_confirmation = None
        self._refresh_approval_bar()
        if not accepted:
            result = self.engine.confirm_pending_tool(False)
            self.output.append(f"<b>ARQEN:</b> {result}")
            self.set_status(tr("READY // CONFIRMATION CANCELLED"))
            return
        self.set_status(self.provider_status(tr("WORKING // RUNNING CONFIRMED TOOL")))
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
        self.set_status(tr("READY // CONFIRMATION RESOLVED"))

    def show_generated_image(self, result: str) -> None:
        image_match = re.search(r"Bild skapad:\s*(.+)$", result)
        if image_match:
            image_path = Path(image_match.group(1).strip()).resolve()
            if image_path.exists():
                image_url = QUrl.fromLocalFile(str(image_path)).toString()
                self.output.append(f"<div style='margin:8px 0;'><img src='{image_url}' width='640'></div>")

    def confirmation_failed(self, message: str) -> None:
        self.append_message(tr("ERROR"), message, CyberpunkGreenTheme.danger)
        self.set_status(tr("ERROR // CONFIRMATION FAILED"))

    def open_settings(self) -> None:
        config = load_provider_config()
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Arqen Settings"))
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
        tabs.addTab(profile_tab, tr("Profile"))
        tabs.addTab(provider_tab, tr("Provider"))
        tabs.addTab(workspace_tab, tr("Workspace"))
        tabs.addTab(fallback_tab, tr("Fallback"))
        tabs.addTab(stats_tab, tr("Statistics"))
        dialog_layout.addWidget(tabs, 1)

        provider = QComboBox()
        provider_items = [(tr("Local Ollama"), "local"), ("Arqen Remote", "arqen-remote"), ("OpenAI", "openai"), ("OpenRouter", "openrouter"), ("Gemini", "gemini"), ("Claude", "claude"), ("Demo", "demo")]
        for label, value in provider_items:
            provider.addItem(label, value)
        provider.setCurrentIndex(max(0, provider.findData(config.name)))
        profile = QComboBox()
        profile.addItem(tr("Private – Ollama"), "private")
        profile.addItem(tr("Fast – OpenRouter"), "fast")
        profile.addItem("Viktigt – OpenAI", "important")
        # The creative preset runs on Gemini; the label used to say OpenRouter.
        profile.addItem(tr("Creative – Gemini"), "creative")
        saved_profile = {"private": "private", "fast": "fast", "important": "important", "creative": "creative"}.get(config.profile_name, "")
        if saved_profile:
            profile.setCurrentIndex(profile.findData(saved_profile))
        profile_form.addRow(tr("Profile"), profile)
        profile_hint = QLabel()
        profile_hint.setWordWrap(True)
        profile_form.addRow(tr("Description"), profile_hint)
        profile_descriptions = {
            "private": tr("Local and private. Uses Ollama without cloud fallback."),
            "fast": tr("Fast everyday profile. Uses OpenRouter without automatic fallback."),
            "important": tr("For important tasks. Uses OpenAI without automatic fallback."),
            "creative": tr("For ideas, writing and creative workflows via Gemini."),
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
        model_search.setPlaceholderText(tr("Search models..."))
        provider_form.addRow(tr("Search models"), model_search)
        model_search.textChanged.connect(lambda text: self.filter_model_choices(model, text))
        model_search.returnPressed.connect(lambda: self.filter_model_choices(model, model_search.text()))
        base_url = QLineEdit(config.base_url)
        timeout = QLineEdit(str(config.timeout))
        api_key = QLineEdit(config.api_key)
        api_key.setEchoMode(QLineEdit.EchoMode.Password)
        provider_form.addRow(tr("Provider"), provider)
        provider_form.addRow(tr("Model"), model)
        provider_form.addRow("URL", base_url)
        provider_form.addRow(tr("API key"), api_key)
        provider_form.addRow(tr("Timeout"), timeout)
        fallback_enabled = QCheckBox(tr("Enable fallback on provider error"))
        fallback_enabled.setChecked(config.fallback_enabled)
        fallback_provider = QComboBox()
        for label, value in provider_items:
            if value != config.name:
                fallback_provider.addItem(label, value)
        fallback_provider.setCurrentIndex(max(0, fallback_provider.findData(config.fallback_provider)))
        fallback_timeout = QLineEdit(str(config.fallback_timeout))
        fallback_form.addRow(tr("Fallback"), fallback_enabled)
        fallback_form.addRow(tr("Fallback provider"), fallback_provider)
        fallback_form.addRow(tr("Fallback timeout (s)"), fallback_timeout)
        provider_info = QLabel(self.provider_overview(fallback_enabled.isChecked()))
        provider_info.setWordWrap(True)
        fallback_form.addRow(tr("Provider status"), provider_info)
        stats_button = QPushButton(tr("VIEW PROVIDER STATISTICS"))
        stats_button.setObjectName("secondaryButton")
        stats_button.clicked.connect(self.show_provider_metrics)
        stats_layout.addWidget(stats_button)
        reset_stats = QPushButton(tr("RESET STATISTICS"))
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

        apply_profile = QPushButton(tr("APPLY PROFILE"))
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
        workspace_form.addRow(tr("Workspace"), workspace)
        browse = QPushButton(tr("BROWSE FOLDER"))
        browse.setObjectName("secondaryButton")
        browse.clicked.connect(lambda: self.choose_workspace(dialog, workspace))
        workspace_form.addRow(browse)
        workspace_hint = QLabel(tr(
            "The folder Arqen reads and writes files in. It only affects tools — "
            "settings, chats and memory remain inside the application "
            "({root}). Leave it empty to use the application folder.",
            root=APP_ROOT,
        ))
        workspace_hint.setWordWrap(True)
        workspace_form.addRow(tr("About"), workspace_hint)

        refresh_models = QPushButton(tr("FETCH MODELS"))
        refresh_models.setObjectName("secondaryButton")
        refresh_models.clicked.connect(lambda: self.load_local_models(model, base_url.text(), api_key.text(), provider.currentData()))
        actions_layout = QHBoxLayout()
        actions_layout.addWidget(refresh_models)

        test_connection = QPushButton(tr("TEST CONNECTION"))
        test_connection.setObjectName("secondaryButton")
        test_connection.clicked.connect(
            lambda: self.test_provider_connection(provider.currentData(), model.currentData() or model.currentText(), base_url.text(), api_key.text())
        )
        actions_layout.addWidget(test_connection)

        save = QPushButton(tr("SAVE"))
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
        # From the config default, not a literal: a hard-coded 10 s here cut
        # real turns short (one measured MiMo turn took 58 s).
        fallback_timeout.setText(str(ProviderConfig().fallback_timeout))

    def provider_overview(self, fallback_enabled: bool | None = None) -> str:
        provider = getattr(self.engine.provider, "provider_name", self.provider_label).upper()
        model = getattr(self.engine.provider, "model", "") or tr("unknown model")
        used = getattr(self.engine.provider, "fallback_used", False)
        if fallback_enabled is True and not used:
            fallback = tr("enabled, not used yet")
        elif fallback_enabled is False:
            fallback = tr("disabled")
        else:
            fallback = tr("currently used") if used else tr("not enabled")
        elapsed = f"{self.last_response_ms / 1000:.1f} s" if self.last_response_ms is not None else tr("no measurement yet")
        metrics = self.provider_metrics._load().get(f"{provider.lower()}/{model}", {})
        avg_ms = metrics.get("total_ms", 0) / metrics.get("requests", 1)
        return tr(
            "Active: {provider} / {model}\nFallback: {fallback}\nLatest response time: {elapsed}\n"
            "Fallback switches: {switches}\nHistory: {requests} responses, average {average:.1f} s",
            provider=provider, model=model, fallback=fallback, elapsed=elapsed,
            switches=self.fallback_count, requests=metrics.get("requests", 0), average=avg_ms / 1000,
        )

    def show_provider_metrics(self) -> None:
        metrics = self.provider_metrics._load()
        if not metrics:
            text = tr("No provider statistics available yet.")
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
                rows.append(tr(
                    "{key}\n  Requests: {requests} | Successful: {successes} | Errors: {errors} | Success rate: {rate:.0f}%\n"
                    "  Average: {average:.1f} s | Fallback: {fallbacks}",
                    key=key, requests=requests, successes=item.get("successes", 0), errors=item.get("errors", 0),
                    rate=success_rate, average=average, fallbacks=item.get("fallbacks", 0),
                ))
            text = "\n\n".join(rows)
        QMessageBox.information(self, tr("Provider statistics"), text)

    def reset_provider_metrics(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("Reset statistics"),
            tr("Delete all saved provider statistics?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.provider_metrics.reset()
            QMessageBox.information(self, tr("Provider statistics"), tr("Provider statistics have been reset."))

    def choose_workspace(self, dialog: QDialog, field: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(dialog, tr("Choose workspace"), field.text() or str(APP_ROOT))
        if chosen:
            field.setText(str(Path(chosen)))

    def save_settings(self, dialog: QDialog, name: str, model: str, base_url: str, timeout: str, api_key: str, fallback_enabled: bool = False, fallback_provider: str = "", fallback_timeout: str = str(ProviderConfig().fallback_timeout), profile_name: str = "", workspace: str = "") -> None:
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
                raise ValueError(tr("Workspace folder does not exist: {path}", path=chosen))
            save_workspace_root(chosen)
            self.provider_label = config.name
            self.profile_name = profile_name
            self.set_status(self.provider_status(tr("READY // PROVIDER UPDATED")))
            dialog.accept()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(dialog, tr("Invalid settings"), str(exc))

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
            QMessageBox.warning(self, tr("Could not fetch models"), str(exc))

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
            model_box.setToolTip(tr("Click FETCH MODELS to load provider models"))
        else:
            model_box.setToolTip(tr("Type or select a model for this provider"))

    def test_provider_connection(self, provider: str, model: str, base_url: str, api_key: str = "") -> None:
        if provider == "demo":
            QMessageBox.information(self, tr("Connection OK"), tr("The demo provider is available."))
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
            QMessageBox.information(self, tr("Connection OK"), tr("Provider responded and the model exists:\n{model}", model=model))
        except Exception as exc:
            QMessageBox.warning(self, tr("Connection failed"), str(exc))

    @staticmethod
    def model_label(model_id: str) -> str:
        kind = "CLOUD" if model_id.lower().endswith(":cloud") else "LOCAL"
        return f"[{kind}] {model_id}"
