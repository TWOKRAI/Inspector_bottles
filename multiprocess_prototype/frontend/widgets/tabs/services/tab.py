# -*- coding: utf-8 -*-
"""ServicesTab — таб управления сервисами по шаблону Settings.

3 колонки + мастер-скролл + QGroupBox-заголовок через ``DiffScrollTabLayout``;
tree-навигация через ``BaseTreeNavTab``. Под родительской веткой «Сервисы»
лежат сервисные секции (камеры, БД, робот, сохранение кадров); top-level
«Нейронные сети» — placeholder для будущих фич. Каждая сервисная секция
держит ``RegisterView`` в content-колонке и три кнопки управления
(Запустить/Остановить/Перезапуск) в action-колонке.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseTreeNavTab
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from ._sections import build_services_sections

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с Settings/Recipes/Processes.
    return DiffScrollTabLayout(title="Сервисы", action_width=160, nav_width=230)


class ServicesTab(BaseTreeNavTab):
    """Таб «Сервисы» — BaseTreeNavTab с секциями сервисов и плейсхолдеров.

    Структурно идентичен SettingsTab: tree-nav слева, action-кнопки секции
    в левой колонке, content-виджет секции — в правой; мастер-скролл общий.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        bus = ctx.action_bus()
        super().__init__(
            title="Сервисы",
            sections=build_services_sections(ctx),
            ctx=ctx,
            layout_factory=_layout_factory,
            bus_change_subscriber=(lambda cb: bus.add_change_callback(cb)) if bus else None,
            parent=parent,
        )
        self.enable_undo_redo(bus)
        self.populate()

    @classmethod
    def create(cls, ctx: "AppContext") -> "ServicesTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    def _tree_object_name(self) -> str:
        return "ServicesTreeNav"
