"""StandardTabLayout — единый шаблон оформления вкладок прототипа.

Layout (слева направо):

    ┌──────────┬─────────┬──────────────────────┬───┐
    │ Top      │ Sub-nav │   Content            │ █ │
    │ actions  │ (опц.)  │   (внутри QScrollArea│ █ │
    │          │         │    — толстый scroll  │ █ │
    │ ......   │         │    справа от темы)   │   │
    │ Bottom   │         │                      │   │
    │ actions  │         │                      │   │
    │ (Undo/   │         │                      │   │
    │  Redo)   │         │                      │   │
    └──────────┴─────────┴──────────────────────┴───┘

Цель — унифицировать все вкладки: action-кнопки слева, подвкладки рядом,
основной контент по центру, толстый scrollbar справа (через QScrollArea).
Undo/Redo живут в нижней части action-колонки через ``enable_undo_redo``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.actions.bus_factory import ActionBus

_DEFAULT_ACTION_WIDTH = 120
_DEFAULT_SUB_NAV_WIDTH = 200
_SUB_NAV_ITEM_HEIGHT = 40
_SUB_NAV_ITEM_SPACING = 4


class StandardTabLayout(QWidget):
    """Стандартный шаблон вкладки: actions | sub-nav | content | scroll.

    Использование:

        tab = StandardTabLayout(show_sub_nav=True)
        tab.add_top_action("save", "Сохранить")
        tab.add_top_action("load", "Загрузить")
        tab.enable_undo_redo(action_bus)
        tab.add_sub_nav_section("a", "Раздел A", widget_a)
        tab.add_sub_nav_section("b", "Раздел B", widget_b)
        tab.action_triggered.connect(self._on_action)

    Если ``show_sub_nav=False``, sub-nav колонка не создаётся, и контент
    задаётся через ``set_content_widget(widget)``.
    """

    action_triggered = Signal(str)
    section_changed = Signal(str)

    def __init__(
        self,
        action_width: int = _DEFAULT_ACTION_WIDTH,
        sub_nav_width: int = _DEFAULT_SUB_NAV_WIDTH,
        show_sub_nav: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._action_width = action_width
        self._sub_nav_width = sub_nav_width
        self._show_sub_nav = show_sub_nav

        self._top_buttons: dict[str, QPushButton] = {}
        self._bottom_buttons: dict[str, QPushButton] = {}
        self._sub_nav_keys: list[str] = []
        self._sub_nav_index: dict[str, int] = {}

        # Undo/Redo (создаются ленниво в enable_undo_redo)
        self._undo_btn: QPushButton | None = None
        self._redo_btn: QPushButton | None = None
        self._action_bus: ActionBus | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # ── Колонка действий (слева) ──────────────────────────────────
        self._action_col = QWidget()
        self._action_col.setObjectName("StandardTabActionColumn")
        self._action_col.setFixedWidth(self._action_width)
        action_layout = QVBoxLayout(self._action_col)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        self._top_actions_layout = QVBoxLayout()
        self._top_actions_layout.setSpacing(6)
        action_layout.addLayout(self._top_actions_layout)

        action_layout.addStretch(1)

        self._bottom_actions_layout = QVBoxLayout()
        self._bottom_actions_layout.setSpacing(6)
        action_layout.addLayout(self._bottom_actions_layout)

        root.addWidget(self._action_col)

        # ── Sub-nav (опц.) ────────────────────────────────────────────
        self._sub_nav: QListWidget | None = None
        # content_stack создаётся лениво при первом add_sub_nav_section()
        # (см. _ensure_content_stack). Так sub-nav может работать в двух режимах:
        # • stack-режим: каждый раздел — своя страница в _content_stack;
        # • external-режим: sub-nav используется как UI-выбор, реальный
        #   контент задаётся через set_content_widget() и общий для всех.
        self._content_stack: QStackedWidget | None = None
        if self._show_sub_nav:
            self._sub_nav = QListWidget()
            self._sub_nav.setObjectName("StandardTabSubNav")
            self._sub_nav.setFixedWidth(self._sub_nav_width)
            self._sub_nav.setSpacing(_SUB_NAV_ITEM_SPACING)
            self._sub_nav.currentRowChanged.connect(self._on_sub_nav_row_changed)
            root.addWidget(self._sub_nav)

        # ── Контент в QScrollArea ─────────────────────────────────────
        # Толстый скролл берётся из глобального QSS темы (см. main.qss).
        self._scroll = QScrollArea()
        self._scroll.setObjectName("StandardTabScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self._scroll, 1)

    def _ensure_content_stack(self) -> QStackedWidget:
        """Создать ``_content_stack`` при первом обращении (lazy)."""
        if self._content_stack is None:
            self._content_stack = QStackedWidget()
            self._scroll.setWidget(self._content_stack)
        return self._content_stack

    # ------------------------------------------------------------------
    # Левая колонка: действия
    # ------------------------------------------------------------------

    def add_top_action(self, action_id: str, label: str) -> QPushButton:
        """Добавить кнопку в верхнюю часть action-колонки."""
        btn = self._make_button(action_id, label)
        self._top_actions_layout.addWidget(btn)
        self._top_buttons[action_id] = btn
        return btn

    def add_bottom_action(self, action_id: str, label: str) -> QPushButton:
        """Добавить кнопку в нижнюю часть action-колонки.

        Bottom-actions прижаты к нижнему краю; сюда автоматически попадают
        Undo/Redo через ``enable_undo_redo``.
        """
        btn = self._make_button(action_id, label)
        self._bottom_actions_layout.addWidget(btn)
        self._bottom_buttons[action_id] = btn
        return btn

    def add_top_widget(self, widget: QWidget) -> None:
        """Добавить произвольный виджет в верхнюю часть action-колонки.

        Полезно для тумблеров и индикаторов, не являющихся кнопками.
        """
        self._top_actions_layout.addWidget(widget)

    def get_button(self, action_id: str) -> QPushButton | None:
        """Вернуть кнопку по ``action_id`` (top или bottom), если есть."""
        return self._top_buttons.get(action_id) or self._bottom_buttons.get(action_id)

    def set_action_enabled(self, action_id: str, enabled: bool) -> None:
        """Включить/отключить кнопку по ``action_id``."""
        btn = self.get_button(action_id)
        if btn is not None:
            btn.setEnabled(enabled)

    def _make_button(self, action_id: str, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.clicked.connect(
            lambda _checked=False, aid=action_id: self.action_triggered.emit(aid)
        )
        return btn

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def enable_undo_redo(self, action_bus: "ActionBus | None") -> None:
        """Создать Undo/Redo кнопки в bottom-actions и привязать к шине.

        Безопасно при ``action_bus is None`` — кнопки создаются disabled
        и не падают; их состояние просто не обновляется.
        """
        if self._undo_btn is not None or self._redo_btn is not None:
            return  # уже включено

        self._action_bus = action_bus

        self._undo_btn = QPushButton("◀ Назад")
        self._undo_btn.setToolTip("Отменить (Ctrl+Z)")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._on_undo_clicked)

        self._redo_btn = QPushButton("Вперёд ▶")
        self._redo_btn.setToolTip("Повторить (Ctrl+Y)")
        self._redo_btn.setEnabled(False)
        self._redo_btn.clicked.connect(self._on_redo_clicked)

        self._bottom_actions_layout.addWidget(self._undo_btn)
        self._bottom_actions_layout.addWidget(self._redo_btn)

        if action_bus is not None:
            action_bus.add_change_callback(self._refresh_undo_redo_state)
            self._refresh_undo_redo_state()

    def _on_undo_clicked(self) -> None:
        if self._action_bus is not None:
            self._action_bus.undo()

    def _on_redo_clicked(self) -> None:
        if self._action_bus is not None:
            self._action_bus.redo()

    def _refresh_undo_redo_state(self) -> None:
        bus = self._action_bus
        if bus is None or self._undo_btn is None or self._redo_btn is None:
            return
        self._undo_btn.setEnabled(bus.can_undo())
        self._redo_btn.setEnabled(bus.can_redo())

    @property
    def undo_button(self) -> QPushButton | None:
        return self._undo_btn

    @property
    def redo_button(self) -> QPushButton | None:
        return self._redo_btn

    # ------------------------------------------------------------------
    # Sub-nav
    # ------------------------------------------------------------------

    def add_sub_nav_section(
        self,
        key: str,
        title: str,
        widget: QWidget | None = None,
    ) -> None:
        """Добавить раздел в sub-nav.

        Только если ``show_sub_nav=True``. Если ``widget`` задан — создаётся
        страница в content-stack (классический stack-режим). Если ``None`` —
        sub-nav используется как чистый UI-выбор; контент задаётся через
        :py:meth:`set_content_widget` и общий для всех разделов.
        """
        assert self._sub_nav is not None, (
            "add_sub_nav_section() требует show_sub_nav=True"
        )
        item = QListWidgetItem(title)
        item.setSizeHint(QSize(0, _SUB_NAV_ITEM_HEIGHT))
        item.setData(Qt.ItemDataRole.UserRole, key)
        self._sub_nav.addItem(item)

        self._sub_nav_keys.append(key)
        if widget is not None:
            stack = self._ensure_content_stack()
            idx = stack.addWidget(widget)
            self._sub_nav_index[key] = idx

    def set_current_section(self, key: str) -> None:
        """Переключить sub-nav на раздел по ключу.

        Работает в обоих режимах. Если контент-stack создан — также
        переключает страницу. Иначе — только эмитит ``section_changed``.
        """
        assert self._sub_nav is not None
        try:
            row = self._sub_nav_keys.index(key)
        except ValueError:
            return
        self._sub_nav.setCurrentRow(row)

    def current_section_key(self) -> str:
        """Ключ текущего sub-nav (пустая строка если нет / не выбран)."""
        if self._sub_nav is None:
            return ""
        row = self._sub_nav.currentRow()
        if row < 0 or row >= len(self._sub_nav_keys):
            return ""
        return self._sub_nav_keys[row]

    def sub_nav_count(self) -> int:
        """Количество разделов sub-nav."""
        return len(self._sub_nav_keys)

    def clear_sub_nav(self) -> None:
        """Удалить все разделы sub-nav и виджеты из стека."""
        if self._sub_nav is None or self._content_stack is None:
            return
        self._sub_nav.blockSignals(True)
        self._sub_nav.clear()
        while self._content_stack.count() > 0:
            w = self._content_stack.widget(0)
            self._content_stack.removeWidget(w)
            if w is not None:
                w.deleteLater()
        self._sub_nav_keys.clear()
        self._sub_nav_index.clear()
        self._sub_nav.blockSignals(False)

    def _on_sub_nav_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._sub_nav_keys):
            return
        key = self._sub_nav_keys[row]
        if self._content_stack is not None and key in self._sub_nav_index:
            self._content_stack.setCurrentIndex(self._sub_nav_index[key])
        self.section_changed.emit(key)

    # ------------------------------------------------------------------
    # Контент без sub-nav
    # ------------------------------------------------------------------

    def set_content_widget(self, widget: QWidget) -> None:
        """Задать центральный виджет.

        Работает в обоих режимах:

        • ``show_sub_nav=False`` — единственный способ задать контент.
        • ``show_sub_nav=True`` — sub-nav используется как UI-выбор (без
          переключения страниц stack'а). ``section_changed`` всё равно
          эмитится, чтобы приложение могло обновить ``widget`` своими
          средствами.

        Если ранее уже было добавление через ``add_sub_nav_section`` со
        страницами, вызов перезапишет содержимое scroll-области.
        """
        self._content_stack = None  # сбрасываем stack, если был
        self._scroll.setWidget(widget)

    # ------------------------------------------------------------------
    # Доступ к внутренним виджетам (для интеграции и тестов)
    # ------------------------------------------------------------------

    @property
    def action_column(self) -> QWidget:
        """Виджет action-колонки (для дополнительного стилирования)."""
        return self._action_col

    @property
    def sub_nav_list(self) -> QListWidget | None:
        """QListWidget sub-nav (None если show_sub_nav=False)."""
        return self._sub_nav

    @property
    def content_stack(self) -> QStackedWidget | None:
        """QStackedWidget контента sub-nav (None если show_sub_nav=False)."""
        return self._content_stack

    @property
    def scroll_area(self) -> QScrollArea:
        """QScrollArea, оборачивающая контент."""
        return self._scroll
