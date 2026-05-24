"""StandardTabLayout — единый шаблон оформления вкладок.

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

Наследник ``_AbstractColumnarTabLayout``. Полностью удовлетворяет
``TabLayoutProtocol`` (runtime_checkable).

См. ADR-126, ADR-127.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSize,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)

from ._abstract_columnar import _AbstractColumnarTabLayout

if TYPE_CHECKING:
    pass

_DEFAULT_ACTION_WIDTH = 120
_DEFAULT_SUB_NAV_WIDTH = 200
_SUB_NAV_ITEM_HEIGHT = 40
_SUB_NAV_ITEM_SPACING = 4


class StandardTabLayout(_AbstractColumnarTabLayout):
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

    Полностью удовлетворяет ``TabLayoutProtocol``.
    """

    action_triggered = Signal(str)

    def __init__(
        self,
        action_width: int = _DEFAULT_ACTION_WIDTH,
        sub_nav_width: int = _DEFAULT_SUB_NAV_WIDTH,
        show_sub_nav: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(action_width=action_width, parent=parent)

        self._sub_nav_width = sub_nav_width
        self._show_sub_nav = show_sub_nav

        self._top_buttons: dict[str, QPushButton] = {}
        self._bottom_buttons: dict[str, QPushButton] = {}
        self._sub_nav_keys: list[str] = []
        self._sub_nav_index: dict[str, int] = {}

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
    # _AbstractColumnarTabLayout — размещение undo/redo
    # ------------------------------------------------------------------

    def _add_undo_redo_buttons(
        self,
        undo: QPushButton,
        redo: QPushButton,
    ) -> None:
        """Разместить кнопки undo/redo в bottom-actions."""
        undo.setText("◀ Назад")
        redo.setText("Вперёд ▶")
        self._bottom_actions_layout.addWidget(undo)
        self._bottom_actions_layout.addWidget(redo)

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
        btn.clicked.connect(lambda _checked=False, aid=action_id: self.action_triggered.emit(aid))
        return btn

    # ------------------------------------------------------------------
    # _AbstractColumnarTabLayout — set_action_widget
    # ------------------------------------------------------------------

    def set_action_widget(self, widget: QWidget) -> None:
        """Задать содержимое action-колонки (виджет в top-области).

        Очищает текущее содержимое ``_top_actions_layout`` и размещает
        переданный виджет. Используется ``BaseTreeNavTab._build_ui()``
        для размещения action-виджета секции.
        """
        # Очистить старые виджеты из top-actions
        while self._top_actions_layout.count():
            item = self._top_actions_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._top_actions_layout.addWidget(widget)

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
        assert self._sub_nav is not None, "add_sub_nav_section() требует show_sub_nav=True"
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
    # TabLayoutProtocol — set_title
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Задать/обновить заголовок layout'а.

        StandardTabLayout не имеет встроенного QGroupBox с заголовком
        (в отличие от DiffScrollTabLayout). Метод добавлен для соответствия
        TabLayoutProtocol. Заголовок устанавливается как windowTitle виджета.
        """
        self.setWindowTitle(text)

    # ------------------------------------------------------------------
    # TabLayoutProtocol — set_nav_widget
    # ------------------------------------------------------------------

    def set_nav_widget(self, widget: QWidget) -> None:
        """Задать навигационный виджет (QTreeWidget, QListWidget, ...).

        Если sub-nav не активен — no-op с предупреждением.
        Если sub-nav уже создан — заменяет встроенный QListWidget
        переданным виджетом в layout'е.

        Для StandardTabLayout основной сценарий — использование встроенного
        sub-nav через ``add_sub_nav_section``. Этот метод нужен для
        совместимости с TabLayoutProtocol (nav-агностичный контракт базы).
        """
        root_layout = self.layout()
        if root_layout is None:
            return

        # Если sub-nav существует — заменяем его на переданный виджет
        if self._sub_nav is not None:
            idx = root_layout.indexOf(self._sub_nav)
            if idx >= 0:
                root_layout.removeWidget(self._sub_nav)
                self._sub_nav.deleteLater()
                self._sub_nav = None
                root_layout.insertWidget(idx, widget)  # type: ignore[arg-type]
                return

        # Если sub-nav не был создан, вставляем перед scroll area
        scroll_idx = root_layout.indexOf(self._scroll)
        if scroll_idx >= 0:
            root_layout.insertWidget(scroll_idx, widget)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # TabLayoutProtocol — register_inner_scrolls
    # ------------------------------------------------------------------

    def register_inner_scrolls(self, widget: QWidget) -> None:
        """Подключить вложенные QScrollArea к синхронизации.

        StandardTabLayout использует стандартный QScrollArea без
        дифференциального скролла, поэтому специальная синхронизация
        не требуется. Метод предоставлен для совместимости с
        TabLayoutProtocol.
        """
        # Стандартный layout не использует дифференциальный скролл,
        # поэтому регистрация не требуется.

    # ------------------------------------------------------------------
    # TabLayoutProtocol — connect_stack / refresh_after_page_change
    # ------------------------------------------------------------------

    def connect_stack(self, stack: QStackedWidget, role: str) -> None:
        """Подписать смену страницы стека на refresh layout'а.

        Для StandardTabLayout подключает ``currentChanged`` стека
        к обновлению widgetResizable на scroll area.
        """
        stack.currentChanged.connect(
            lambda _index, r=role: self.refresh_after_page_change(r),
        )

    def refresh_after_page_change(self, role: str) -> None:
        """Принудительно пересчитать scroll area после смены страницы.

        Toggle widgetResizable заставляет QScrollArea пересчитать размер
        виджета и диапазон скроллбара.
        """
        self._scroll.setWidgetResizable(False)
        self._scroll.setWidgetResizable(True)

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
