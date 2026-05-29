# -*- coding: utf-8 -*-
"""BaseTreeNavTab --- QWidget-каркас вкладки с tree-навигацией.

Наследует ``BaseColumnarTab`` (nav-агностичную базу) и добавляет
tree-навигацию по ``list[SectionSpec]``:

* Строит ``QTreeWidget`` из списка ``SectionSpec``.
* Управляет секциями через ``TreeNavTabPresenter``.
* Поддерживает ленивое создание секций.
* Ретранслирует события секций (dirty, saved).

Подклассы (``SettingsTab``, ``RecipesTab``, ...) добавляют:

* Конкретный ``layout_factory`` (например ``DiffScrollTabLayout``);
* Собственный presenter (``_make_presenter`` hook);
* Объектные имена для QSS (``_tree_object_name`` hook).

Сигналы:
    section_changed(str):           ключ активной секции после навигации
                                    (наследован от BaseColumnarTab).
    section_dirty_changed(str, bool): (key, dirty) --- ретранслирован от секции.
    section_data_saved(str, dict):  (key, data) --- ретранслирован от секции.

См. ADR-126, Phase 3, Phase 6b.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)

from .base_columnar_tab import BaseColumnarTab
from .current_page_stack import CurrentPageStack
from .nav_tree_utils import (
    build_nav_tree_from_specs,
    collapse_other_branches,
    select_tree_key,
)
from .tree_nav_presenter import TreeNavTabPresenter

if TYPE_CHECKING:
    from .section_protocol import SectionProtocol
    from .section_spec import SectionSpec
    from .tab_layout_protocol import TabLayoutProtocol, UndoRedoController

logger = logging.getLogger(__name__)


class BaseTreeNavTab(BaseColumnarTab):
    """QWidget-каркас вкладки с tree-навигацией.

    Принимает список ``SectionSpec`` и автоматически строит UI: nav-дерево,
    content-стек, action-стек. Навигация делегирована ``TreeNavTabPresenter``.

    Подкласс **обязан** передать ``layout_factory`` (или получит ``RuntimeError``).
    """

    # Сигналы наружу (section_changed наследуется от BaseColumnarTab)
    section_dirty_changed = Signal(str, bool)
    section_data_saved = Signal(str, dict)

    def __init__(
        self,
        *,
        title: str,
        sections: "list[SectionSpec[Any]]",
        ctx: Any,
        layout_factory: "Callable[[], TabLayoutProtocol] | None" = None,
        bus_change_subscriber: "Callable[[Callable[[], None]], None] | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать вкладку с tree-навигацией.

        Args:
            title:                  заголовок (отображается в layout GroupBox).
            sections:               декларации секций.
            ctx:                    контекст приложения (пробрасывается в factory).
            layout_factory:         фабрика layout'а (TabLayoutProtocol).
            bus_change_subscriber:  функция ``lambda cb: bus.add_change_callback(cb)``
                                    для подписки callback'ов секций на ActionBus.
                                    ``None`` --- секции не подписываются.
            parent:                 родительский виджет.
        """
        # --- Сохранить данные ДО super().__init__, т.к. _build_nav_widget()
        #     вызывается из BaseColumnarTab.__init__ и требует _sections_specs.
        self._sections_specs: list[SectionSpec[Any]] = list(sections)
        self._bus_change_subscriber = bus_change_subscriber

        # --- BaseColumnarTab.__init__ ---
        # Вызовет _create_content_stack() → CurrentPageStack,
        # _build_nav_widget() → QTreeWidget с items,
        # set_nav_widget, set_content_widget, set_title, QVBoxLayout(self).
        super().__init__(
            title=title,
            ctx=ctx,
            layout_factory=layout_factory,
            parent=parent,
        )

        # --- Action stack (SectionSpec-specific, не в BaseColumnarTab) ---
        self._action_stack = CurrentPageStack()

        # Пустая action-страница (для секций без кнопок)
        empty_page = QWidget()
        empty_idx = self._action_stack.addWidget(empty_page)

        # --- Presenter ---
        self._presenter = self._make_presenter()
        self._presenter.register_action_page("_empty", empty_idx)

        # --- Наполнение секциями ---
        for spec in self._sections_specs:
            if spec.lazy:
                self._presenter.register_lazy_section(spec.key)
            else:
                section = spec.factory(ctx)
                self._attach_section(section, spec.key)

        # --- Собрать action layout ---
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(0)
        action_layout.addWidget(self._action_stack, 1)

        self._tab_layout.set_action_widget(action_widget)

        # --- Подключить авто-refresh при смене страниц ---
        self._tab_layout.connect_stack(self._content_stack, "content")
        self._tab_layout.connect_stack(self._action_stack, "action")

    # ------------------------------------------------------------------
    # Хуки BaseColumnarTab --- реализация
    # ------------------------------------------------------------------

    def _create_content_stack(self) -> QStackedWidget:
        """Вернуть ``CurrentPageStack`` для smart-sizing в DiffScrollTabLayout."""
        return CurrentPageStack()

    def _build_nav_widget(self) -> QWidget:
        """Построить QTreeWidget с items из ``_sections_specs``."""
        tree = QTreeWidget()
        tree.setObjectName(self._tree_object_name())
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setIndentation(16)
        tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        tree.currentItemChanged.connect(self._on_tree_item_changed)

        # Заполнить nav-tree по SectionSpec
        build_nav_tree_from_specs(tree, self._sections_specs)

        # Сохранить ссылку для публичного API
        self._tree_nav = tree
        return tree

    def _on_nav_changed(self, key: str) -> None:
        """Делегировать смену навигации в presenter."""
        self._presenter.on_tree_item_changed(key)

    # ------------------------------------------------------------------
    # Хуки для подклассов
    # ------------------------------------------------------------------

    def _tree_object_name(self) -> str:
        """ObjectName для QTreeWidget навигации.

        Подкласс может переопределить (например ``SettingsTab`` вернёт
        ``"SettingsTreeNav"`` для сохранения QSS-контракта).
        """
        return "TreeNavWidget"

    def _make_presenter(self) -> TreeNavTabPresenter:
        """Создать presenter для вкладки.

        Подкласс может вернуть конкретный presenter (например
        ``SettingsPresenter``), если нужна app-specific логика.
        """
        return TreeNavTabPresenter(view=self, rm=None, ui=None)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def populate(self) -> None:
        """Навести фокус на первую top-level секцию.

        Вызывается явно после ``__init__``. Подкласс может переопределить
        для дополнительных действий (подписка на bus и т.п.).
        """
        # Найти первую top-level секцию
        for spec in self._sections_specs:
            if spec.parent_key is None:
                self._presenter.navigate_to(spec.key)
                break

    def enable_undo_redo(self, bus: "UndoRedoController | None") -> None:
        """Делегировать создание undo/redo кнопок в layout.

        Принимает framework ``ActionBus`` либо prototype domain-диспетчер
        (``services.commands``, G.4.4) — оба удовлетворяют ``UndoRedoController``.
        """
        self._tab_layout.enable_undo_redo(bus)

    @property
    def presenter(self) -> TreeNavTabPresenter:
        """Presenter вкладки (для подклассов и тестов)."""
        return self._presenter

    @property
    def tree_nav(self) -> QTreeWidget:
        """QTreeWidget навигации (для тестов)."""
        return self._tree_nav

    @property
    def content_stack(self) -> CurrentPageStack:
        """Content стек (для подклассов)."""
        # _content_stack создаётся через _create_content_stack() → CurrentPageStack
        return self._content_stack  # type: ignore[return-value]

    @property
    def action_stack(self) -> CurrentPageStack:
        """Action стек (для подклассов)."""
        return self._action_stack

    # ------------------------------------------------------------------
    # View Protocol --- методы, вызываемые presenter'ом
    # ------------------------------------------------------------------

    def set_content_index(self, index: int) -> None:
        """Переключить content stack на указанный индекс."""
        self._content_stack.setCurrentIndex(index)

    def set_action_index(self, index: int) -> None:
        """Переключить action stack на указанный индекс."""
        self._action_stack.setCurrentIndex(index)

    def select_tree_key(self, key: str) -> None:
        """Выбрать элемент nav-дерева по ключу."""
        select_tree_key(self._tree_nav, key)

    def create_lazy_section(self, key: str) -> None:
        """Создать ленивую секцию по ключу (вызывается presenter'ом).

        Ищет ``SectionSpec`` с данным ключом, вызывает фабрику,
        регистрирует секцию. Подкласс может переопределить для
        app-specific lazy-логики (например admin-панели в Settings).
        """
        spec = next((s for s in self._sections_specs if s.key == key), None)
        if spec is None:
            logger.warning("Неизвестный ключ ленивой секции: %s", key)
            return

        section = spec.factory(self._ctx)
        content_idx, action_idx = self._attach_section(section, key)
        self._presenter.notify_lazy_section_created(
            key,
            section.widget(),
            action_idx,
            content_idx,
        )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _attach_section(
        self,
        section: "SectionProtocol",
        key: str,
    ) -> tuple[int, int]:
        """Зарегистрировать секцию: контент, action-кнопки, presenter, события.

        Returns:
            (content_idx, action_idx)
        """
        # Content page
        content_idx = self._content_stack.addWidget(section.widget())
        self._presenter.register_content_page(key, content_idx)

        # Action page
        buttons = section.action_buttons()
        if buttons:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(12)
            for btn in buttons:
                page_layout.addWidget(btn)
            page_layout.addStretch(1)
            action_idx = self._action_stack.addWidget(page)
            self._presenter.register_action_page(key, action_idx)
        else:
            action_idx = self._presenter.get_action_index("_empty")

        # Реестр секции
        self._presenter.register_section(section)

        # Инжект presenter'а (если spec задаёт presenter_factory) ---
        # ПЕРЕД _connect_section_events, т.к. bus_change_callback() секции
        # обращается к self._presenter, который должен уже быть установлен.
        self._apply_presenter_factory(section, key)

        # Подключение событий (SectionWithEvents)
        self._connect_section_events(section, key)

        return content_idx, action_idx

    def _apply_presenter_factory(
        self,
        section: "SectionProtocol",
        key: str,
    ) -> None:
        """Если у spec есть presenter_factory --- создать presenter и inject в секцию.

        Ищет SectionSpec с данным ключом. Если у spec задана presenter_factory
        и у секции есть метод set_presenter --- создаёт presenter через фабрику
        и передаёт его в секцию. Через getattr + callable, чтобы не ломать
        секции без setter'а (адаптеры admin-панелей).
        """
        spec = next((s for s in self._sections_specs if s.key == key), None)
        if spec is None or spec.presenter_factory is None:
            return
        set_presenter = getattr(section, "set_presenter", None)
        if not callable(set_presenter):
            return
        presenter = spec.presenter_factory(self._ctx, section)
        set_presenter(presenter)

    def _connect_section_events(
        self,
        section: "SectionProtocol",
        key: str,
    ) -> None:
        """Подключить события секции (dirty, saved, bus_change) если доступны."""
        # section_dirty_changed
        dirty_signal = getattr(section, "section_dirty_changed", None)
        if dirty_signal is not None:
            try:
                dirty_signal.connect(
                    lambda dirty, k=key: self.section_dirty_changed.emit(k, dirty),
                )
            except (AttributeError, TypeError):
                pass

        # section_data_saved
        saved_signal = getattr(section, "section_data_saved", None)
        if saved_signal is not None:
            try:
                saved_signal.connect(
                    lambda data, k=key: self.section_data_saved.emit(k, data),
                )
            except (AttributeError, TypeError):
                pass

        # bus_change_callback
        bus_cb_fn = getattr(section, "bus_change_callback", None)
        if bus_cb_fn is not None and self._bus_change_subscriber is not None:
            try:
                callback = bus_cb_fn()
                if callback is not None:
                    self._bus_change_subscriber(callback)
            except (AttributeError, TypeError):
                pass

    def _on_tree_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        """Смена текущего элемента дерева --- делегировать presenter'у."""
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        # Авто-expand/collapse: раскрыть ветку текущего, свернуть остальные
        collapse_other_branches(self._tree_nav, current)
        # Вся логика (в т.ч. ленивое создание панелей) --- через _on_nav_changed
        # (единый полиморфный хук BaseColumnarTab, а не прямой вызов presenter)
        self._on_nav_changed(key)
        # Сигнал наружу (наследован от BaseColumnarTab)
        self.section_changed.emit(key)
