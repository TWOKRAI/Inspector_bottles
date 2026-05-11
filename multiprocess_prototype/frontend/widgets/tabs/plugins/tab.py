"""PluginsTab — таб настройки плагинов.

Композиция: MasterDetailLayout (список слева, RegisterView/InfoCard справа).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from multiprocess_prototype.frontend.widgets.primitives import MasterDetailLayout
from multiprocess_prototype.frontend.forms import RegisterView

from .detail_panels import PluginInfoCard
from .presenter import PluginsPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class PluginsTab(QWidget):
    """Таб настройки плагинов — master-detail.

    Слева: список всех плагинов с фильтром по категории и поиском.
    Справа: RegisterView для плагинов с registers, PluginInfoCard для остальных.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = PluginsPresenter(ctx)
        self._detail_cache: dict[str, QWidget] = {}  # кэш виджетов деталей

        self._init_ui()
        self._populate()

        # Подписаться на ActionBus для обновления виджетов при undo/redo
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.add_change_callback(self._on_bus_changed)

    @classmethod
    def create(cls, ctx: "AppContext") -> "PluginsTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    def _init_ui(self) -> None:
        """Построить layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Заголовок
        header = QLabel("Плагины")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Master-detail
        self._master_detail = MasterDetailLayout(search_placeholder="Поиск плагина...")
        self._master_detail.selection_changed.connect(self._on_plugin_selected)
        layout.addWidget(self._master_detail, stretch=1)

    def _populate(self) -> None:
        """Заполнить список плагинов."""
        items = self._presenter.list_plugins()
        self._master_detail.set_items(items)

        categories = self._presenter.get_categories()
        self._master_detail.set_categories(categories)

        # Создать placeholder для пустого detail
        placeholder = QLabel("Выберите плагин из списка слева")
        placeholder.setStyleSheet("color: #888; font-size: 14px;")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._master_detail.set_detail_widget("__placeholder__", placeholder)

    def _on_plugin_selected(self, plugin_name: str) -> None:
        """Обработать выбор плагина — показать detail панель."""
        if plugin_name in self._detail_cache:
            # Уже создан — просто переключить через set_detail_widget (он перепоказывает)
            self._master_detail.set_detail_widget(plugin_name, self._detail_cache[plugin_name])
            return

        info = self._presenter.get_plugin_info(plugin_name)

        if info.get("has_registers"):
            # Плагин с registers → RegisterView
            fields = self._presenter.get_register_fields(plugin_name)
            if fields:
                detail: QWidget = RegisterView(fields)
                # Подключить field_changed → ActionBus
                detail.field_changed.connect(self._on_field_changed)
                # PR3: весь RegisterView — read-only без tabs.plugins.edit.
                from multiprocess_prototype.frontend.widgets.access import (
                    bind_edit_permission,
                )
                _auth = self._ctx.auth
                bind_edit_permission(
                    detail,
                    "tabs.plugins.edit",
                    _auth.state if _auth is not None else None,
                )
            else:
                detail = PluginInfoCard(info)
        else:
            # Плагин без registers → PluginInfoCard
            detail = PluginInfoCard(info)

        self._detail_cache[plugin_name] = detail
        self._master_detail.set_detail_widget(plugin_name, detail)

    def _on_field_changed(
        self, register_name: str, field_name: str, old_value: object, new_value: object,
    ) -> None:
        """Изменение параметра плагина → ActionBus.execute(field_set)."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
        action = V2ActionBuilder.field_set_timed(
            register_name, field_name, new_value, old_value,
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
        # Найти RegisterView с этим plugin_name
        register_name = action.register_name or ""
        detail = self._detail_cache.get(register_name)
        if detail is None or not isinstance(detail, RegisterView):
            return
        # Определить значение для восстановления
        value = (
            action.backward_patch.get("value")
            if event_type == "undo"
            else action.forward_patch.get("value")
        )
        key = f"{register_name}.{action.field_name}"
        detail.set_editor_value(key, value)
