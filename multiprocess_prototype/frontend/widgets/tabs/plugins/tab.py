# -*- coding: utf-8 -*-
"""PluginsTab — таб настройки плагинов.

Шаблон визуально и архитектурно идентичен Settings/Services:
3 колонки (actions / nav / content) + мастер-скролл + QGroupBox-заголовок
через ``DiffScrollTabLayout``; дерево плагинов во второй колонке через
``BaseTreeNavTab``. Над деревом — поле поиска (фильтрация по подстроке).
В первой колонке — тогглер режима отображения (Карточки / Таблица):

- ``Cards``  — стандартное поведение BaseTreeNavTab: выбран плагин → справа
  его detail-виджет (``RegisterView`` или ``PluginInfoCard``).
- ``Table``  — общая таблица всех плагинов (имя / категория / есть registers
  / описание); навигация по дереву игнорируется до возврата в Cards.

Структура nav:
    ▾ Источники
        capture
        ...
    ▾ Обработка
        color_mask
        grayscale
        ...

Все скроллы — глобальный master-scrollbar из ``DiffScrollTabLayout``;
внутренние скроллбары дерева и таблицы скрыты (``ScrollBarAlwaysOff``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseTreeNavTab
from multiprocess_framework.modules.frontend_module.widgets.tabs.nav_tree_utils import (
    build_nav_tree_from_specs,
)
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from ._sections import build_plugin_sections
from .presenter import PluginsPresenter

if TYPE_CHECKING:
    from typing import Any

    from multiprocess_framework.modules.registers_module import RegistersManager


# Размеры колонок: nav шире в 1.5× по сравнению с Recipes/Processes/Services
# (230 × 1.5 = 345) — дерево с категориями требует больше места.
_NAV_WIDTH = 345


def _layout_factory() -> DiffScrollTabLayout:
    return DiffScrollTabLayout(title="Плагины", action_width=160, nav_width=_NAV_WIDTH)


_TABLE_COLUMNS = ["Имя", "Категория", "Registers", "Описание"]


class PluginsTab(BaseTreeNavTab):
    """Таб «Плагины» — BaseTreeNavTab + DiffScrollTabLayout с тогглером Cards/Table.

    Расширения над BaseTreeNavTab:
    - ``_build_nav_widget`` обёрнут в контейнер с QLineEdit (поиск) над QTreeWidget;
    - content-колонка — два уровня stack: внешний ``_root_stack`` переключает
      между Cards (внутренний content_stack базы) и Table (общая таблица);
    - action-колонка — ``ViewModeToggle`` поверх стандартного ``_action_stack``.
    """

    def __init__(
        self,
        services: AppServices,
        *,
        plugin_manager: "Any" = None,
        registers_manager: "RegistersManager | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        self._services = services
        self._plugin_manager = plugin_manager
        self._registers_manager = registers_manager
        self._presenter_local = PluginsPresenter(
            services, plugin_manager=plugin_manager, registers_manager=registers_manager
        )
        # Поле поиска создаётся в _build_nav_widget (вызывается из super().__init__).
        self._search: QLineEdit | None = None
        self._tree_nav: QTreeWidget | None = None  # type: ignore[assignment]
        # Текущий режим отображения (Cards/Table).
        self._view_mode: ViewMode = ViewMode.CARDS

        # ActionBus bridge (TODO Phase G (G.4): domain commands).
        _bus_accessor = getattr(services.commands, "action_bus", None)
        bus = _bus_accessor() if callable(_bus_accessor) else None
        super().__init__(
            title="Плагины",
            sections=build_plugin_sections(
                services,
                plugin_manager=plugin_manager,
                registers_manager=registers_manager,
                open_sandbox_cb=self.open_sandbox,
            ),
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
            layout_factory=_layout_factory,
            bus_change_subscriber=(lambda cb: bus.add_change_callback(cb)) if bus else None,
            parent=parent,
        )

        # Table view добавляем как ещё одну страницу в content_stack базы.
        # В Table-режиме форсируем переключение на эту страницу; tree-навигация
        # в Table-режиме блокируется через override set_content_index().
        self._table_widget = self._build_table_widget()
        self._table_idx = self._content_stack.addWidget(self._table_widget)

        # Заменить action_widget: добавить ViewModeToggle сверху над action_stack базы.
        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        new_action_widget = QWidget()
        action_layout = QVBoxLayout(new_action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)
        action_layout.addWidget(self._toggle)
        action_layout.addWidget(self._action_stack, 1)
        self._tab_layout.set_action_widget(new_action_widget)

        self.enable_undo_redo(bus)
        self.populate()

        # Task 2.6 — подписать каталог на сигнал catalog_updated от секции «Пути».
        # Секция __paths__ не lazy, значит виджет уже создан к этому моменту.
        paths_section = self._presenter.section("__paths__")
        if paths_section is not None:
            paths_widget = paths_section.widget()
            catalog_updated = getattr(paths_widget, "catalog_updated", None)
            if catalog_updated is not None:
                catalog_updated.connect(self.refresh_catalog)

    @classmethod
    def create(
        cls,
        services: AppServices,
        runtime: RuntimeDeps = RuntimeDeps(),
    ) -> "PluginsTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        plugin_manager + registers_manager -- runtime layer, не AppServices (G.2).
        """
        return cls(
            services,
            plugin_manager=runtime.plugin_manager,
            registers_manager=runtime.registers_manager,
        )

    # ------------------------------------------------------------------ #
    #  Task 2.6 — обновление каталога после rescan                        #
    # ------------------------------------------------------------------ #

    def open_sandbox(self, plugin_name: str, sandbox_widget: QWidget) -> None:
        """Открыть sandbox-виджет для плагина в content-панели.

        Добавляет виджет в content_stack если его там ещё нет,
        затем переключает на него. Используется как callback из _PluginSection.

        Args:
            plugin_name: имя плагина (для идентификации).
            sandbox_widget: готовый PluginSandboxWidget (singleton per plugin).
        """
        # Проверяем — виджет уже в stack?
        stack = self._content_stack
        found = False
        for i in range(stack.count()):
            if stack.widget(i) is sandbox_widget:
                found = True
                break
        if not found:
            stack.addWidget(sandbox_widget)
        stack.setCurrentWidget(sandbox_widget)

    def refresh_catalog(self) -> None:
        """Перестроить дерево навигации и таблицу после rescan плагинов.

        Вызывается по сигналу catalog_updated от PathsSubtabWidget.
        Полная перестройка (diff-алгоритм не нужен для MVP).
        """
        if self._tree_nav is None:
            return

        # Пересобрать список секций с актуальным каталогом плагинов
        # Передаём open_sandbox как callback — секции получат кнопку «Тест».
        self._sections_specs = build_plugin_sections(
            self._services, plugin_manager=self._plugin_manager, open_sandbox_cb=self.open_sandbox
        )

        # Очистить дерево и перестроить заново
        self._tree_nav.clear()
        build_nav_tree_from_specs(self._tree_nav, self._sections_specs)
        self._tree_nav.expandAll()

        # Если активен режим Table — обновить таблицу тоже
        if self._view_mode == ViewMode.TABLE:
            self._refresh_table()

    # ------------------------------------------------------------------ #
    #  Hooks BaseTreeNavTab                                                #
    # ------------------------------------------------------------------ #

    def _tree_object_name(self) -> str:
        return "PluginsTreeNav"

    def _build_nav_widget(self) -> QWidget:
        """Контейнер: QLineEdit (поиск) над QTreeWidget с категориями плагинов.

        ``self._tree_nav`` указывает на QTreeWidget — базовый класс
        BaseTreeNavTab работает с ним напрямую (currentItemChanged → presenter).
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск плагина...")
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        tree = QTreeWidget()
        tree.setObjectName(self._tree_object_name())
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setIndentation(16)
        # Глобальный скролл — внутренние скроллбары дерева скрыты,
        # колесо перехватывает DiffScrollTabLayout через event filter.
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.currentItemChanged.connect(self._on_tree_item_changed)

        build_nav_tree_from_specs(tree, self._sections_specs)
        # Раскрыть все категории по умолчанию — короткие списки плагинов.
        tree.expandAll()

        self._tree_nav = tree
        layout.addWidget(tree, 1)
        return container

    # ------------------------------------------------------------------ #
    #  Search filter                                                       #
    # ------------------------------------------------------------------ #

    def _on_search_changed(self, text: str) -> None:
        """Скрыть листы по подстроке; категорию скрыть, если все её дети скрыты."""
        assert self._tree_nav is not None
        needle = text.strip().lower()
        for i in range(self._tree_nav.topLevelItemCount()):
            cat_item = self._tree_nav.topLevelItem(i)
            if cat_item is None:
                continue
            visible_children = 0
            for j in range(cat_item.childCount()):
                child = cat_item.child(j)
                if child is None:
                    continue
                label = child.text(0).lower()
                hidden = bool(needle) and needle not in label
                child.setHidden(hidden)
                if not hidden:
                    visible_children += 1
            # Категория видима, если есть хоть один видимый ребёнок или поиск пуст.
            cat_item.setHidden(bool(needle) and visible_children == 0)

    # ------------------------------------------------------------------ #
    #  View mode (Cards / Table)                                           #
    # ------------------------------------------------------------------ #

    def _on_view_mode_changed(self, mode_str: str) -> None:
        mode = ViewMode(mode_str)
        self._view_mode = mode
        if mode == ViewMode.TABLE:
            self._refresh_table()
            self._content_stack.setCurrentIndex(self._table_idx)
        else:
            # Восстановить страницу текущего выбранного плагина (если есть).
            assert self._tree_nav is not None
            cur = self._tree_nav.currentItem()
            if cur is not None:
                key = cur.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(key, str) and key in self.presenter._page_index:
                    self._content_stack.setCurrentIndex(self.presenter._page_index[key])

    def set_content_index(self, index: int) -> None:  # type: ignore[override]
        """Override: в Table-режиме игнорировать переключения от tree-навигации.

        Tree-клик на плагине вызывает presenter → set_content_index, но
        в Table-режиме контент должен оставаться на таблице.
        """
        if self._view_mode == ViewMode.TABLE:
            return
        super().set_content_index(index)

    # ------------------------------------------------------------------ #
    #  Table view                                                          #
    # ------------------------------------------------------------------ #

    def _build_table_widget(self) -> QTableWidget:
        tbl = QTableWidget(0, len(_TABLE_COLUMNS))
        tbl.setHorizontalHeaderLabels(_TABLE_COLUMNS)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        h = tbl.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        return tbl

    def _refresh_table(self) -> None:
        """Перезаполнить таблицу актуальным состоянием реестра плагинов."""
        plugins = self._presenter_local.list_plugins()
        self._table_widget.setRowCount(len(plugins))
        for row, (name, _display, category) in enumerate(plugins):
            info = self._presenter_local.get_plugin_info(name)
            cat_title = PluginsPresenter.CATEGORY_TITLES.get(category, category)
            self._table_widget.setItem(row, 0, QTableWidgetItem(name))
            self._table_widget.setItem(row, 1, QTableWidgetItem(cat_title))
            self._table_widget.setItem(row, 2, QTableWidgetItem("✓" if info.get("has_registers") else "—"))
            self._table_widget.setItem(row, 3, QTableWidgetItem(info.get("description", "")))
        # Подогнать высоту строк под содержимое.
        self._table_widget.resizeRowsToContents()

    # ------------------------------------------------------------------ #
    #  Совместимость со старым _on_tree_item_changed                       #
    # ------------------------------------------------------------------ #

    def _on_tree_item_changed(  # type: ignore[override]
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        """Override для использования self._tree_nav (а не self._tree_nav из базы)."""
        # Делегируем в реализацию базы, она уже использует self._tree_nav.
        super()._on_tree_item_changed(current, previous)
