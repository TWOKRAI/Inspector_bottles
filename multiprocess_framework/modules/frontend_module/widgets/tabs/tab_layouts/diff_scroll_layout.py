"""DiffScrollTabLayout — шаблон вкладки с дифференциальным скроллом.

Layout:

    ┌──────────────┬──────────────┬────────────────────┬───┐
    │  [scroll]    │ ┌──────────┐ │  [scroll]          │ █ │ ← мастер-скроллбар
    │  Actions     │ │  Title   │ │  Content           │ █ │
    │  (dynamic)   │ └──────────┘ │                    │   │
    │              │  [scroll]    │                    │   │
    │              │  Nav items   │                    │   │
    ├──────────────┤              │                    │   │
    │ [static]     │              │                    │   │
    │  [◀] [▶]    │              │                    │   │
    └──────────────┴──────────────┴────────────────────┴───┘

Один мастер-скроллбар справа управляет тремя колонками синхронно.
Каждая колонка останавливается на своей высоте контента (дифференциальный
скролл). Кнопки undo/redo статичны — не скроллятся.

Использование:

    layout = DiffScrollTabLayout(title="Настройки")
    layout.set_action_widget(my_buttons)
    layout.set_nav_widget(my_tree)
    layout.set_content_widget(my_content)
    layout.enable_undo_redo(action_bus)

Наследник ``_AbstractColumnarTabLayout``. См. ADR-126, ADR-127.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QChildEvent, QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ._abstract_columnar import _AbstractColumnarTabLayout

if TYPE_CHECKING:
    from PySide6.QtGui import QWheelEvent


_DEFAULT_ACTION_WIDTH = 120
_DEFAULT_NAV_WIDTH = 200


class DiffScrollTabLayout(_AbstractColumnarTabLayout):
    """Шаблон вкладки с дифференциальным скроллом.

    Сигналы:
        section_changed(str): для совместимости с потребителями.
    """

    def __init__(
        self,
        title: str = "",
        action_width: int = _DEFAULT_ACTION_WIDTH,
        nav_width: int = _DEFAULT_NAV_WIDTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(action_width=action_width, parent=parent)
        self._nav_width = nav_width

        # Scroll sync
        self._syncing = False
        self._scroll_areas: list[QScrollArea] = []
        self._redirected: set[int] = set()
        # Последнее значение мастера — для расчёта delta в _on_master_changed.
        # Дельта применяется к каждой колонке независимо, поэтому короткая
        # колонка не «висит» на своём max, ожидая пока мастер дойдёт до её
        # абсолютного значения сверху — она сразу пойдёт вверх вместе с мастером.
        self._last_master_value = 0

        self._build_ui(title)

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self, title: str) -> None:
        root = QHBoxLayout(self)
        # 15px отступ сверху единый для всех трёх колонок и мастер-скроллбара —
        # визуально отделяет верх содержимого от рамки таба.
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(12)

        # === Левая колонка: scroll(actions) + static(undo/redo) ===
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)

        self._action_scroll = self._make_scroll_area("DiffScrollActions")
        self._action_scroll.setFixedWidth(self._action_width)
        left_col.addWidget(self._action_scroll, 1)

        # Статичная зона (не скроллится)
        self._static_bottom = QWidget()
        self._static_bottom.setFixedWidth(self._action_width)
        self._static_bottom_layout = QHBoxLayout(self._static_bottom)
        self._static_bottom_layout.setContentsMargins(4, 4, 4, 4)
        self._static_bottom_layout.setSpacing(4)
        left_col.addWidget(self._static_bottom)

        root.addLayout(left_col)

        # === Средняя колонка: QGroupBox с заголовком + nav (scroll) ===
        self._nav_group = QGroupBox(title)
        self._nav_group.setObjectName("DiffScrollNavGroup")
        self._nav_group.setFixedWidth(self._nav_width)
        if not title:
            self._nav_group.setTitle("")

        nav_group_lay = QVBoxLayout(self._nav_group)
        nav_group_lay.setContentsMargins(13, 19, 13, 13)
        nav_group_lay.setSpacing(0)

        # Nav scroll area внутри group box
        self._nav_scroll = self._make_scroll_area("DiffScrollNav")

        self._nav_container = QWidget()
        nav_lay = QVBoxLayout(self._nav_container)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(4)

        # Placeholder для навигационного виджета
        self._nav_placeholder = QWidget()
        nav_lay.addWidget(self._nav_placeholder, 1)

        self._nav_scroll.setWidget(self._nav_container)
        nav_group_lay.addWidget(self._nav_scroll, 1)

        root.addWidget(self._nav_group, 0)

        # === Правая колонка: content (scroll) ===
        self._content_scroll = self._make_scroll_area("DiffScrollContent")
        root.addWidget(self._content_scroll, 1)

        # === Мастер-скроллбар (ширина управляется темой в main.qss) ===
        self._master_sb = QScrollBar(Qt.Orientation.Vertical)
        self._master_sb.setObjectName("DiffScrollMaster")
        self._master_sb.valueChanged.connect(self._on_master_changed)
        root.addWidget(self._master_sb)

        # Регистрация scroll areas + перехват wheel
        self._scroll_areas = [
            self._action_scroll,
            self._nav_scroll,
            self._content_scroll,
        ]
        for sa in self._scroll_areas:
            vbar = sa.verticalScrollBar()
            vbar.rangeChanged.connect(lambda _mn, _mx: self._update_master_range())
            self._install_wheel_redirect(sa.viewport())

    # ------------------------------------------------------------------
    # Scroll sync
    # ------------------------------------------------------------------

    def _make_scroll_area(self, name: str) -> QScrollArea:
        """Создать QScrollArea со скрытыми скроллбарами."""
        sa = QScrollArea()
        sa.setObjectName(name)
        sa.setWidgetResizable(True)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        # Прозрачный фон задаётся в main.qss через objectName (DiffScrollLeft/Right/...)
        return sa

    def _install_wheel_redirect(self, viewport: QWidget) -> None:
        """Установить event filter для перехвата wheel → мастер."""
        vid = id(viewport)
        if vid in self._redirected:
            return
        self._redirected.add(vid)
        viewport.installEventFilter(self)

    def _redirect_nested_wheels(self, widget: QWidget) -> None:
        """Перехват wheel у вложенных QAbstractScrollArea (QTreeWidget и т.д.).

        Прозрачные QScrollArea (например RegisterView._cards_widget) дополнительно
        включаются в синхронизацию с мастером, чтобы их контент тоже двигался
        диф-скроллом и тормозил на своих границах. QTreeWidget/QTableWidget
        и прочие самостоятельные QAbstractScrollArea только перехватывают wheel.
        """
        for child in widget.findChildren(QAbstractScrollArea):
            self._install_wheel_redirect(child.viewport())
            if type(child) is QScrollArea and child not in self._scroll_areas:
                self._scroll_areas.append(child)
                vbar = child.verticalScrollBar()
                vbar.rangeChanged.connect(
                    lambda _mn, _mx: self._update_master_range(),
                )
                self._update_master_range()

    def eventFilter(self, obj: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            self._forward_wheel(event)  # type: ignore[arg-type]
            return True
        # ChildAdded на content-виджете: автоматически подхватить вложенные
        # QScrollArea в новых страницах стека (например при addWidget в
        # QStackedWidget). Защита от зацикливания — внутри
        # _redirect_nested_wheels/_install_wheel_redirect по id(viewport).
        if event.type() == QEvent.Type.ChildAdded and isinstance(event, QChildEvent):
            child = event.child()
            if isinstance(child, QWidget):
                self._redirect_nested_wheels(child)
        return super().eventFilter(obj, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Wheel в любом месте шаблона → мастер-скроллбар."""
        self._forward_wheel(event)

    def _forward_wheel(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = max(1, self._master_sb.singleStep())
        # 3 строки за одно деление колеса
        self._master_sb.setValue(
            self._master_sb.value() - (delta // 120) * step * 3,
        )

    def _on_master_changed(self, value: int) -> None:
        if self._syncing:
            return
        delta = value - self._last_master_value
        self._last_master_value = value
        self._syncing = True
        # Дельта-скролл: каждая колонка сдвигается на delta от текущего
        # значения и клампится в [0, max]. Колонки, у которых maximum
        # меньше самой длинной колонки («короткие» — action/nav), идут
        # с половинной скоростью — иначе они доезжают до концов слишком
        # быстро и долго стоят, пока длинный content догоняет.
        master_max = self._master_sb.maximum()
        for sa in self._scroll_areas:
            vbar = sa.verticalScrollBar()
            if vbar.maximum() < master_max:
                # Половинная скорость для коротких колонок.
                # // 2 даёт целочисленную дельту; знак сохраняется.
                column_delta = delta // 2 if delta >= 0 else -((-delta) // 2)
            else:
                column_delta = delta
            new_value = vbar.value() + column_delta
            vbar.setValue(max(0, min(new_value, vbar.maximum())))
        self._syncing = False

    def _update_master_range(self) -> None:
        if self._syncing:
            return
        max_range = 0
        for sa in self._scroll_areas:
            max_range = max(max_range, sa.verticalScrollBar().maximum())
        self._master_sb.blockSignals(True)
        self._master_sb.setRange(0, max_range)
        self._master_sb.setPageStep(max(1, self.height()))
        self._master_sb.setSingleStep(20)
        self._master_sb.blockSignals(False)
        # Синхронизируем baseline дельта-скролла с реальным value мастера
        # (setRange мог склампить value), иначе следующее valueChanged
        # выдаст ложную дельту и колонки прыгнут.
        self._last_master_value = self._master_sb.value()
        # Скроллбар виден всегда — при max_range == 0 handle занимает 100%
        # высоты рельса (нечего скроллить, но место под скролл зарезервировано).
        self._master_sb.setVisible(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_master_range()

    # ------------------------------------------------------------------
    # _AbstractColumnarTabLayout — размещение undo/redo
    # ------------------------------------------------------------------

    def _add_undo_redo_buttons(
        self,
        undo: QPushButton,
        redo: QPushButton,
    ) -> None:
        """Разместить кнопки undo/redo в статичной зоне (не скроллится)."""
        undo.setObjectName("DiffScrollUndo")
        redo.setObjectName("DiffScrollRedo")
        self._static_bottom_layout.addWidget(undo)
        self._static_bottom_layout.addWidget(redo)

    # ------------------------------------------------------------------
    # Public API — наполнение колонок
    # ------------------------------------------------------------------

    def set_title(self, text: str) -> None:
        """Задать/обновить текст заголовка QGroupBox."""
        self._nav_group.setTitle(text)

    @property
    def nav_group(self) -> QGroupBox:
        """QGroupBox навигационной колонки."""
        return self._nav_group

    def set_action_widget(self, widget: QWidget) -> None:
        """Задать содержимое скроллируемой части левой колонки."""
        self._action_scroll.setWidget(widget)

    def set_nav_widget(self, widget: QWidget) -> None:
        """Задать навигационный виджет (QTreeWidget, QListWidget, …)."""
        nav_lay = self._nav_container.layout()
        idx = nav_lay.indexOf(self._nav_placeholder)
        nav_lay.removeWidget(self._nav_placeholder)
        self._nav_placeholder.deleteLater()
        nav_lay.insertWidget(idx, widget)
        self._nav_placeholder = widget
        # Перехватываем wheel на вложенных scroll areas
        self._redirect_nested_wheels(widget)

    def set_content_widget(self, widget: QWidget) -> None:
        """Задать виджет правой колонки (основной контент).

        Дополнительно устанавливает event filter на ChildAdded: когда в
        content-стек добавляется новая страница (addWidget), layout
        автоматически подключает вложенные QScrollArea к диф-скроллу.
        """
        self._content_scroll.setWidget(widget)
        # Перехватываем wheel у вложенных scroll areas
        self._redirect_nested_wheels(widget)
        # Автоматическая подписка на новые дочерние виджеты
        widget.installEventFilter(self)

    def register_inner_scrolls(self, widget: QWidget) -> None:
        """Подключить вложенные QScrollArea/QAbstractScrollArea к диф-скроллу.

        Вызывается потребителем после ленивого добавления страниц/виджетов
        в content или nav (например QStackedWidget наполняется уже после
        set_content_widget). Прозрачные QScrollArea будут участвовать
        в синхронизации с мастером, остальные — только перехват wheel.
        """
        self._redirect_nested_wheels(widget)

    # ------------------------------------------------------------------
    # Публичный API — управление скроллом при смене страниц
    # ------------------------------------------------------------------

    def refresh_after_page_change(self, role: Literal["content", "action"]) -> None:
        """Принудительно пересчитать scroll area после смены страницы стека.

        Toggle widgetResizable заставляет QScrollArea пересчитать размер
        виджета и диапазон скроллбара. Затем обновляется мастер-скроллбар.

        Заменяет ручной доступ к ``_content_scroll.setWidgetResizable(...)``
        и ``_update_master_range()`` — потребителю не нужно знать о приватных
        атрибутах.

        Args:
            role: ``"content"`` или ``"action"`` — какую колонку обновить.
        """
        sa = self._content_scroll if role == "content" else self._action_scroll
        sa.setWidgetResizable(False)
        sa.setWidgetResizable(True)
        self._update_master_range()

    def connect_stack(
        self,
        stack: QStackedWidget,
        role: Literal["content", "action"],
    ) -> None:
        """Автоматически подписать смену страницы стека на refresh_after_page_change.

        Потребителю не нужно вручную подключать ``stack.currentChanged``
        к внутренней логике layout — достаточно одного вызова:

            layout.connect_stack(content_stack, "content")
            layout.connect_stack(action_stack, "action")

        Args:
            stack: QStackedWidget, чьи страницы нужно обновлять.
            role:  ``"content"`` или ``"action"`` — роль стека.
        """
        stack.currentChanged.connect(
            lambda _index, r=role: self.refresh_after_page_change(r),
        )

    # ------------------------------------------------------------------
    # Доступ к внутренним виджетам
    # ------------------------------------------------------------------

    @property
    def action_scroll(self) -> QScrollArea:
        """QScrollArea левой колонки (actions)."""
        return self._action_scroll

    @property
    def nav_scroll(self) -> QScrollArea:
        """QScrollArea средней колонки (nav)."""
        return self._nav_scroll

    @property
    def content_scroll(self) -> QScrollArea:
        """QScrollArea правой колонки (content)."""
        return self._content_scroll

    @property
    def master_scrollbar(self) -> QScrollBar:
        """Мастер-скроллбар (правый край)."""
        return self._master_sb

    @property
    def static_bottom(self) -> QWidget:
        """Статичная зона внизу левой колонки."""
        return self._static_bottom
