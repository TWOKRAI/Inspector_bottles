# -*- coding: utf-8 -*-
"""PluginsTab — таб настройки плагинов.

Шаблон визуально и архитектурно идентичен Recipes/Processes/Settings:
3 колонки (actions / nav / content) + мастер-скролл + QGroupBox-заголовок
через ``DiffScrollTabLayout``; динамический список плагинов во второй колонке
через ``BaseListNavTab``. Над списком плагинов — поле поиска (фильтрация
по подстроке в display-тексте). Категория плагина включена в display-текст
(``"name (Категория)"``). Action-колонка пуста — плагины редактируются
через RegisterView в content-колонке, без отдельных команд.

Каждому nav-ключу соответствует свой detail-виджет:
- ``RegisterView`` — если у плагина есть register fields;
- ``PluginInfoCard`` — иначе (просто информационная карточка).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.frontend.forms import RegisterView
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .detail_panels import PluginInfoCard
from .presenter import PluginsPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с Settings/Recipes/Processes/Services.
    return DiffScrollTabLayout(title="Плагины", action_width=160, nav_width=230)


class PluginsTab(BaseListNavTab):
    """Таб «Плагины» — BaseListNavTab + DiffScrollTabLayout.

    Структурно идентичен Recipes/Processes: tree-/list-nav слева, search над
    списком плагинов, content-виджет — справа. Каждый плагин получает свой
    detail-виджет (``RegisterView`` для плагинов с registers,
    ``PluginInfoCard`` иначе) — создаётся лениво в ``_create_item_widget``.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        self._presenter = PluginsPresenter(ctx)
        # Кэш detail-виджетов (key → QWidget) для исторической совместимости тестов.
        self._detail_cache: dict[str, QWidget] = {}
        # Поле поиска (создаётся в _build_nav_widget).
        self._search: QLineEdit | None = None

        super().__init__(
            title="Плагины",
            ctx=ctx,
            layout_factory=_layout_factory,
            parent=parent,
        )

        # Авто-refresh content scroll при смене активной страницы.
        self._tab_layout.connect_stack(self._content_stack, "content")

        # Undo/Redo в статичной зоне (как Recipes).
        bus = ctx.action_bus() if hasattr(ctx, "action_bus") else None
        self._tab_layout.enable_undo_redo(bus)

        # Подписка на ActionBus для обновления виджетов при undo/redo.
        if bus is not None:
            bus.add_change_callback(self._on_bus_changed)

        # Заполнить список и выбрать первый плагин.
        self._sync_nav()

    @classmethod
    def create(cls, ctx: "AppContext") -> "PluginsTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    # ------------------------------------------------------------------ #
    #  BaseListNavTab hooks                                                #
    # ------------------------------------------------------------------ #

    def _build_nav_widget(self) -> QWidget:
        """Контейнер: QLineEdit (поиск) над QListWidget (список плагинов).

        ``self._nav_widget`` указывает на QListWidget — базовый класс
        BaseListNavTab работает с ним напрямую (add_item / remove_item /
        currentItemChanged → _on_list_selection_changed).
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск плагина...")
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        nav = QListWidget()
        nav.setObjectName("PluginsNavList")
        nav.currentItemChanged.connect(self._on_list_selection_changed)
        self._nav_widget = nav
        layout.addWidget(nav, 1)

        return container

    def _create_item_widget(self, key: str) -> QWidget:
        """Лениво построить detail-виджет для плагина с данным ключом."""
        info = self._presenter.get_plugin_info(key)

        if info.get("has_registers"):
            fields = self._presenter.get_register_fields(key)
            if fields:
                form_ctx = self._build_form_ctx(key)
                detail: QWidget = RegisterView(fields, form_ctx=form_ctx)
                # field_changed → ActionBus (для legacy-полей без form_ctx).
                detail.field_changed.connect(self._on_field_changed)

                # PR3: весь RegisterView — read-only без tabs.plugins.edit.
                from multiprocess_prototype.frontend.widgets.access import (
                    bind_edit_permission,
                )

                _auth = getattr(self._ctx, "auth", None)
                bind_edit_permission(
                    detail,
                    "tabs.plugins.edit",
                    _auth.state if _auth is not None else None,
                )
            else:
                detail = PluginInfoCard(info)
        else:
            detail = PluginInfoCard(info)

        self._detail_cache[key] = detail
        return detail

    # ------------------------------------------------------------------ #
    #  Search filter                                                       #
    # ------------------------------------------------------------------ #

    def _on_search_changed(self, text: str) -> None:
        """Скрыть/показать элементы списка по подстроке в display-тексте."""
        assert self._nav_widget is not None
        needle = text.strip().lower()
        for i in range(self._nav_widget.count()):
            item = self._nav_widget.item(i)
            if item is None:
                continue
            label = item.text().lower()
            item.setHidden(bool(needle) and needle not in label)

    # ------------------------------------------------------------------ #
    #  Nav populate                                                        #
    # ------------------------------------------------------------------ #

    def _sync_nav(self) -> None:
        """Заполнить навигацию плагинами из реестра."""
        assert self._nav_widget is not None
        self._nav_widget.blockSignals(True)
        self._nav_widget.clear()
        while self._content_stack.count() > 0:
            w = self._content_stack.widget(0)
            self._content_stack.removeWidget(w)
            if w is not None:
                w.deleteLater()
        self._key_to_item.clear()
        self._key_to_index.clear()
        self._detail_cache.clear()
        self._nav_widget.blockSignals(False)

        for name, display, _category in self._presenter.list_plugins():
            self.add_item(name, display)

        # Авто-выбор первого плагина (если есть).
        if self._nav_widget.count() > 0:
            first = self._nav_widget.item(0)
            if first is not None:
                key = first.data(Qt.ItemDataRole.UserRole)
                if isinstance(key, str):
                    self.select_item(key)

    # ------------------------------------------------------------------ #
    #  ActionBus integration                                               #
    # ------------------------------------------------------------------ #

    def _build_form_ctx(self, plugin_name: str) -> FormContext | None:  # noqa: ARG002
        """Собрать FormContext для binding-aware RegisterView."""
        return self._ctx.form_context()

    def _on_field_changed(
        self,
        register_name: str,
        field_name: str,
        old_value: object,
        new_value: object,
    ) -> None:
        """Изменение параметра плагина → ActionBus.execute(field_set)."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

        action = V2ActionBuilder.field_set_timed(
            register_name,
            field_name,
            new_value,
            old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.execute(action)

    def _on_bus_changed(self) -> None:
        """Callback от ActionBus — обновить виджеты при undo/redo."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        detail = self._detail_cache.get(register_name)
        if detail is None or not isinstance(detail, RegisterView):
            return
        value = action.backward_patch.get("value") if event_type == "undo" else action.forward_patch.get("value")
        key = f"{register_name}.{action.field_name}"
        detail.set_editor_value(key, value)
