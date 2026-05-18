# -*- coding: utf-8 -*-
"""_AbstractColumnarTabLayout — общая база layout'ов вкладок.

Содержит:
- Action-колонку (top/bottom зоны) с поддержкой Undo/Redo.
- Nav-агностичный слот ``set_nav_widget(QWidget)`` — принимает любой виджет
  (QTreeWidget, QListWidget, произвольный QWidget). Конкретная реализация
  layout'а может уточнить тип, но контракт базы — ``QWidget``.
- Абстрактные методы ``set_content_widget``, ``set_title``.
- Сигнал ``section_changed(str)`` — для совместимости с потребителями.

Наследники: ``DiffScrollTabLayout``, ``StandardTabLayout``.

See also: ADR-126, ADR-127, Phase 6a.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QPushButton,
    QStackedWidget,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.bus import ActionBus

_DEFAULT_ACTION_WIDTH = 120


class _AbstractColumnarTabLayout(QWidget):
    """Общая база для layout'ов вкладок с колоночной структурой.

    Подклассы реализуют конкретную стратегию скролла/навигации,
    но общая action-колонка и undo/redo — здесь.

    Примечание: ``ABC`` mixin невозможен из-за metaclass conflict с
    ``QWidget`` (Shiboken). ``@abstractmethod`` используется декоративно —
    для документации обязательности переопределения; runtime enforcement
    отсутствует.

    Сигналы:
        section_changed(str): эмитится при смене раздела (nav → content).
    """

    section_changed = Signal(str)

    def __init__(
        self,
        action_width: int = _DEFAULT_ACTION_WIDTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._action_width = action_width

        # Undo/Redo (создаются лениво в enable_undo_redo)
        self._undo_btn: QPushButton | None = None
        self._redo_btn: QPushButton | None = None
        self._action_bus: ActionBus | None = None

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def enable_undo_redo(self, action_bus: ActionBus | None) -> None:
        """Создать кнопки Undo/Redo в bottom-зоне action-колонки.

        Безопасно при ``action_bus is None`` — кнопки создаются disabled
        и не падают; их состояние просто не обновляется.
        """
        if self._undo_btn is not None:
            return

        self._action_bus = action_bus

        self._undo_btn = QPushButton("◀")
        self._undo_btn.setToolTip("Отменить (Ctrl+Z)")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._on_undo)

        self._redo_btn = QPushButton("▶")
        self._redo_btn.setToolTip("Повторить (Ctrl+Y)")
        self._redo_btn.setEnabled(False)
        self._redo_btn.clicked.connect(self._on_redo)

        self._add_undo_redo_buttons(self._undo_btn, self._redo_btn)

        if action_bus is not None:
            action_bus.add_change_callback(self._refresh_undo_redo)
            self._refresh_undo_redo()

    @abstractmethod
    def _add_undo_redo_buttons(
        self,
        undo: QPushButton,
        redo: QPushButton,
    ) -> None:
        """Разместить кнопки undo/redo в UI. Реализуется подклассом."""
        ...

    def _on_undo(self) -> None:
        if self._action_bus is not None:
            self._action_bus.undo()

    def _on_redo(self) -> None:
        if self._action_bus is not None:
            self._action_bus.redo()

    def _refresh_undo_redo(self) -> None:
        bus = self._action_bus
        if bus is None or self._undo_btn is None:
            return
        self._undo_btn.setEnabled(bus.can_undo())
        if self._redo_btn is not None:
            self._redo_btn.setEnabled(bus.can_redo())

    @property
    def undo_button(self) -> QPushButton | None:
        return self._undo_btn

    @property
    def redo_button(self) -> QPushButton | None:
        return self._redo_btn

    # ------------------------------------------------------------------
    # Nav-агностичный слот
    # ------------------------------------------------------------------

    @abstractmethod
    def set_nav_widget(self, widget: QWidget) -> None:
        """Задать навигационный виджет (QTreeWidget, QListWidget, ...).

        Контракт базы — ``QWidget``; конкретные layout'ы могут уточнять
        тип, но обязаны принимать произвольный QWidget.
        """
        ...

    # ------------------------------------------------------------------
    # Абстрактные методы — наполнение колонок
    # ------------------------------------------------------------------

    @abstractmethod
    def set_title(self, text: str) -> None:
        """Задать/обновить заголовок layout'а."""
        ...

    @abstractmethod
    def set_action_widget(self, widget: QWidget) -> None:
        """Задать содержимое action-колонки (виджет в top-области)."""
        ...

    @abstractmethod
    def set_content_widget(self, widget: QWidget) -> None:
        """Задать виджет основного контента."""
        ...

    # ------------------------------------------------------------------
    # Методы TabLayoutProtocol — scroll sync
    # ------------------------------------------------------------------

    @abstractmethod
    def register_inner_scrolls(self, widget: QWidget) -> None:
        """Подключить вложенные QScrollArea к синхронизации."""
        ...

    @abstractmethod
    def connect_stack(self, stack: QStackedWidget, role: str) -> None:
        """Подписать смену страницы стека на refresh layout'а."""
        ...

    @abstractmethod
    def refresh_after_page_change(self, role: str) -> None:
        """Принудительно пересчитать scroll area после смены страницы."""
        ...
