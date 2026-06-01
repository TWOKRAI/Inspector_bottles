# -*- coding: utf-8 -*-
"""ProcessCard — насыщенная карточка процесса (ds-card).

Визуал: градиентная ds-card с цветной полосой категории слева, крупным
заголовком + статус-пилюлей, строкой метрик (FPS/Latency/PID) и кнопками-иконками
действий справа (▶ ⏸ ↻ 🗑). Стилизуется через qss по role="process-card" и
динамическим свойствам category/status.

Виджет «глупый»: принимает данные, эмитит ``action_clicked(entity_id, action_id)``.
Метрики/статус обновляются извне (presenter напрямую или GuiStateBindings).
Экспонирует ``indicator``, ``metric_label(key)``, ``pill`` для привязок.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.primitives import StatusIndicator


@dataclass(frozen=True)
class CardButton:
    """Описание кнопки-иконки действия в карточке."""

    action_id: str
    symbol: str
    tooltip: str


# Дефолтный набор действий процесса.
_DEFAULT_ACTIONS: tuple[CardButton, ...] = (
    CardButton("start", "▶", "Запустить"),
    CardButton("stop", "⏸", "Остановить"),
    CardButton("restart", "↻", "Перезапустить"),
    CardButton("delete", "🗑", "Удалить"),
)

# Действия, скрытые для защищённого процесса.
_PROTECTED_HIDDEN = frozenset({"stop", "delete"})

# Статус → русский текст пилюли.
_STATUS_TEXT = {
    "running": "работает",
    "ready": "готов",
    "stopped": "остановлен",
    "created": "создан",
    "starting": "запуск",
    "error": "ошибка",
    "unknown": "—",
}

# Метрики, отображаемые в строке (порядок сохраняется).
_METRIC_KEYS = ("FPS", "Latency", "PID", "Uptime")


class ProcessCard(QFrame):
    """Насыщенная карточка одного процесса."""

    action_clicked = Signal(str, str)  # (entity_id, action_id)

    def __init__(
        self,
        *,
        entity_id: str,
        title: str,
        category: str = "utility",
        protected: bool = False,
        actions: tuple[CardButton, ...] = _DEFAULT_ACTIONS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entity_id = entity_id
        self.setObjectName("ProcessCard")
        self.setProperty("role", "process-card")
        self.setProperty("category", category)
        self.setProperty("status", "unknown")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        root.addLayout(self._build_header(title, protected, actions))
        root.addWidget(self._build_metrics_row())

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_header(self, title: str, protected: bool, actions: tuple[CardButton, ...]) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._indicator = StatusIndicator(size=14)
        header.addWidget(self._indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("ProcessCardTitle")
        header.addWidget(self._title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._pill = QLabel(_STATUS_TEXT["unknown"])
        self._pill.setObjectName("ProcessCardPill")
        self._pill.setProperty("status", "unknown")
        self._pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._pill, 0, Qt.AlignmentFlag.AlignVCenter)

        header.addStretch(1)

        # Кнопки-иконки действий.
        self._action_buttons: dict[str, QPushButton] = {}
        for act in actions:
            if protected and act.action_id in _PROTECTED_HIDDEN:
                continue
            btn = QPushButton(act.symbol)
            btn.setObjectName("ProcessCardIconButton")
            btn.setToolTip(act.tooltip)
            btn.setFixedSize(56, 56)  # ×4 площади от прежних 28×28 (по запросу владельца)
            _font = btn.font()
            _font.setPointSize(20)  # крупнее символ под увеличенную кнопку
            btn.setFont(_font)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, aid=act.action_id: self.action_clicked.emit(self._entity_id, aid)
            )
            header.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self._action_buttons[act.action_id] = btn

        return header

    def _build_metrics_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("ProcessCardMetrics")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(22, 0, 0, 0)  # отступ под полосу категории
        layout.setSpacing(16)

        self._metric_labels: dict[str, QLabel] = {}
        for key in _METRIC_KEYS:
            cell = QLabel(f"{key} —")
            cell.setObjectName("ProcessCardMetric")
            self._metric_labels[key] = cell
            layout.addWidget(cell)
        layout.addStretch(1)
        return row

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def indicator(self) -> StatusIndicator:
        """Индикатор статуса (для GuiStateBindings.bind ... set_state)."""
        return self._indicator

    def metric_label(self, key: str) -> QLabel | None:
        """QLabel метрики по ключу (FPS/Latency/PID) — для привязок."""
        return self._metric_labels.get(key)

    def set_status(self, state: str) -> None:
        """Обновить индикатор + текст/цвет статус-пилюли."""
        self._indicator.set_state(state)
        text = _STATUS_TEXT.get(state, state)
        self._pill.setText(text)
        self._pill.setProperty("status", state)
        self.setProperty("status", state)
        self._repolish(self._pill)
        self._repolish(self)

    def set_metric(self, key: str, value: str) -> None:
        """Обновить значение одной метрики (FPS/Latency/PID)."""
        label = self._metric_labels.get(key)
        if label is not None:
            label.setText(f"{key} {value}")

    def set_metrics(self, metrics: dict[str, str]) -> None:
        """Обновить несколько метрик разом."""
        for key, value in metrics.items():
            self.set_metric(key, value)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        """Пере-применить qss после смены dynamic property."""
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
