# multiprocess_prototype/frontend/widgets/settings_tab/history_section.py
"""
HistorySectionWidget — секция Настроек «История действий».

Заменяет dropdown «История ▼» из шапки. Показывает последние Actions из ActionBus,
по двойному клику — undo_to(action_id).
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    Qt,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QListWidget, QListWidgetItem

_HISTORY_LIMIT = 50


class HistorySectionWidget(QWidget):
    """Секция «История действий» в Настройках."""

    def __init__(self, action_bus: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = action_bus
        self._subscribed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("История действий")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("Двойной клик по строке — откат до выбранного действия.")
        hint.setObjectName("MutedLabel")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_activated)
        layout.addWidget(self._list, 1)

        controls = QHBoxLayout()
        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.clicked.connect(self._refresh)
        self._btn_undo = QPushButton("Откатить выбранное")
        self._btn_undo.clicked.connect(self._undo_selected)
        controls.addWidget(self._btn_refresh)
        controls.addWidget(self._btn_undo)
        controls.addStretch()
        layout.addLayout(controls)

        self._refresh()
        self._subscribe()

    # --------------------------------------------------------------
    # bus subscription
    # --------------------------------------------------------------

    def _subscribe(self) -> None:
        if self._subscribed or self._bus is None:
            return
        cb = getattr(self._bus, "add_change_callback", None)
        if cb is not None:
            cb(self._refresh)
            self._subscribed = True

    def _unsubscribe(self) -> None:
        if not self._subscribed or self._bus is None:
            return
        cb = getattr(self._bus, "remove_change_callback", None)
        if cb is not None:
            cb(self._refresh)
        self._subscribed = False

    # --------------------------------------------------------------
    # rendering
    # --------------------------------------------------------------

    def _refresh(self) -> None:
        self._list.clear()
        if self._bus is None:
            self._list.addItem("ActionBus недоступен")
            return
        history_fn = getattr(self._bus, "history", None)
        if history_fn is None:
            self._list.addItem("ActionBus не поддерживает history()")
            return
        try:
            actions = history_fn(_HISTORY_LIMIT) or []
        except Exception:  # noqa: BLE001
            actions = []
        if not actions:
            self._list.addItem("История пуста")
            return
        for i, action in enumerate(reversed(actions)):
            desc = self._action_label(action)
            label = f"{i + 1}. {desc}"
            if i == 0:
                label = f"● {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, getattr(action, "action_id", None))
            self._list.addItem(item)

    @staticmethod
    def _action_label(action: Any) -> str:
        desc = getattr(action, "description", None)
        if desc:
            return str(desc)
        action_type = getattr(action, "action_type", None)
        if action_type is not None:
            return str(getattr(action_type, "value", action_type))
        return "<action>"

    # --------------------------------------------------------------
    # actions
    # --------------------------------------------------------------

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self._undo_to_item(item)

    def _undo_selected(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._undo_to_item(item)

    def _undo_to_item(self, item: QListWidgetItem) -> None:
        if self._bus is None:
            return
        aid = item.data(Qt.ItemDataRole.UserRole)
        if not aid:
            return
        undo_to = getattr(self._bus, "undo_to", None)
        if undo_to is not None:
            undo_to(aid)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt API naming
        self._unsubscribe()
        super().closeEvent(event)
