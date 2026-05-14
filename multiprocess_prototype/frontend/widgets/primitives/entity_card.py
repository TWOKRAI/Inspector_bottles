"""EntityCard — карточка сущности с индикатором, метриками и действиями.

Универсальный виджет для отображения любой сущности с состоянием.
Не импортирует ничего из multiprocess_prototype.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .status_indicator import StatusIndicator


@dataclass
class CardAction:
    """Описание кнопки действия для EntityCard."""

    action_id: str
    label: str
    enabled: bool = True


class EntityCard(QFrame):
    """Карточка сущности: статус + заголовок + метрики + кнопки.

    Layout::

        QFrame
          QHBoxLayout
            StatusIndicator (12×12)
            QVBoxLayout (info)
              QLabel title (bold)
              QFormLayout metrics
            QHBoxLayout (actions)
              QPushButton × N
    """

    action_clicked = Signal(str, str)  # (entity_id, action_id)

    def __init__(
        self,
        entity_id: str,
        title: str,
        actions: list[CardAction] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EntityCard")
        self._entity_id = entity_id
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # --- виджеты ---
        self._indicator = StatusIndicator(size=12)
        self._title_label = QLabel(title)
        self._title_label.setObjectName("EntityCardTitle")

        # Метрики: key → QLabel(value)
        self._metrics_layout = QFormLayout()
        self._metrics_layout.setContentsMargins(0, 0, 0, 0)
        self._metric_labels: dict[str, QLabel] = {}

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(self._title_label)
        info_layout.addLayout(self._metrics_layout)

        # Кнопки действий
        actions_layout = QVBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        self._action_buttons: dict[str, QPushButton] = {}
        for act in actions or []:
            btn = QPushButton(act.label)
            btn.setEnabled(act.enabled)
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda checked=False, aid=act.action_id: self.action_clicked.emit(self._entity_id, aid))
            actions_layout.addWidget(btn)
            self._action_buttons[act.action_id] = btn
        actions_layout.addStretch()

        # Основной layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 6, 8, 6)
        main_layout.addWidget(self._indicator)
        main_layout.addLayout(info_layout, stretch=1)
        main_layout.addLayout(actions_layout)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    @property
    def entity_id(self) -> str:
        """Идентификатор сущности."""
        return self._entity_id

    def set_status(self, state: str) -> None:
        """Установить статус (делегирует StatusIndicator)."""
        self._indicator.set_state(state)

    def set_title(self, title: str) -> None:
        """Обновить заголовок карточки."""
        self._title_label.setText(title)

    def set_metrics(self, metrics: dict[str, str]) -> None:
        """Обновить key-value метрики.

        Если ключ уже есть — обновить текст, иначе — добавить row.
        """
        for key, value in metrics.items():
            if key in self._metric_labels:
                self._metric_labels[key].setText(value)
            else:
                val_label = QLabel(value)
                self._metric_labels[key] = val_label
                key_label = QLabel(f"{key}:")
                key_label.setObjectName("EntityCardKey")
                self._metrics_layout.addRow(key_label, val_label)

    def set_action_enabled(self, action_id: str, enabled: bool) -> None:
        """Включить/отключить кнопку действия."""
        btn = self._action_buttons.get(action_id)
        if btn is not None:
            btn.setEnabled(enabled)
