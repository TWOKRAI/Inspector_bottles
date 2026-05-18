# -*- coding: utf-8 -*-
"""SettingsPresenter — тонкая обёртка над TreeNavTabPresenter.

Универсальная логика навигации, реестра секций и ленивых узлов вынесена
в `TreeNavTabPresenter` (framework). Здесь — app-specific:

* набор top-level секций и дочерних узлов «Администрация»;
* `populate()` — конкретный порядок страниц для view Settings;
* координация undo/redo через `AppContext.action_bus()`;
* алиасы `*_admin_panel` для обратной совместимости с view-API таба.

См. ADR-126.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    TreeNavTabPresenter,
)

from .view import SettingsView

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)

# Дочерние узлы «Администрация»
_ADMIN_CHILDREN: list[tuple[str, str]] = [
    ("users", "Пользователи"),
    ("roles", "Роли"),
    ("sessions", "Сессии"),
    ("audit_log", "Audit log"),
]

# Top-level секции (кроме admin_dashboard, который строится отдельно)
_TOP_SECTIONS: list[tuple[str, str]] = [
    ("system_settings", "Настройки системы"),
    ("interface_settings", "Настройка интерфейса"),
    ("appearance", "Оформление"),
    ("history", "История"),
]


class SettingsPresenter(TreeNavTabPresenter[SettingsView, None]):
    """Презентер таба Settings.

    Наследует универсальную навигацию у `TreeNavTabPresenter` и добавляет
    конкретный список секций, app-specific `populate()` и подписку
    на `ActionBus` для undo/redo.
    """

    def __init__(self, *, view: SettingsView, rm=None, ui=None, ctx: "AppContext") -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._ctx = ctx

    # ------------------------------------------------------------------
    # Конфигурация навигации
    # ------------------------------------------------------------------

    def admin_children(self) -> list[tuple[str, str]]:
        """Список (ключ, название) дочерних узлов «Администрация»."""
        return list(_ADMIN_CHILDREN)

    def top_sections(self) -> list[tuple[str, str]]:
        """Список (ключ, название) top-level секций."""
        return list(_TOP_SECTIONS)

    def populate(self) -> None:
        """Заполнить навигацию и content stack через методы view.

        Presenter знает ЧТО и в каком порядке создать; view — КАК
        (создаёт конкретные Qt-виджеты).
        """
        self._view.build_nav_tree(_TOP_SECTIONS, _ADMIN_CHILDREN)
        for key, _ in _ADMIN_CHILDREN:
            self.register_lazy_section(key)
        self._view.add_admin_dashboard_page(_ADMIN_CHILDREN)
        self._view.add_system_settings_page()
        self._view.add_interface_settings_page()
        self._view.add_appearance_page()
        self._view.add_history_page()
        self.navigate_to("system_settings")

    # ------------------------------------------------------------------
    # Undo/Redo
    # ------------------------------------------------------------------

    def on_bus_change(self) -> None:
        """Обновить состояние кнопок Undo/Redo по текущему ActionBus."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        self._view.set_undo_enabled(bus.can_undo())
        self._view.set_redo_enabled(bus.can_redo())
