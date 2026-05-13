# -*- coding: utf-8 -*-
"""SettingsPresenter — навигация, реестр секций, undo/redo для Settings таба.

Презентер НЕ импортирует Qt-классы напрямую. Все вызовы UI выполняются
через SettingsView Protocol.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    SectionProtocol,
    TabPresenterBase,
)

from .view import SettingsView

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)


class SettingsPresenter(TabPresenterBase[SettingsView, None]):
    """Презентер Settings таба.

    Отвечает за:
    - навигацию по секциям (tree item → content stack + action stack)
    - реестр секций (SectionProtocol)
    - undo/redo state (через view)
    - ленивое создание панелей администрации

    НЕ импортирует Qt. Работает исключительно через SettingsView Protocol.
    """

    def __init__(
        self,
        *,
        view: SettingsView,
        rm=None,
        ui=None,
        ctx: "AppContext",
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._ctx = ctx

        # Реестр зарегистрированных секций
        self._sections: dict[str, SectionProtocol] = {}

        # Текущий активный ключ секции
        self._current_key: str | None = None

        # Маппинг ключ → индекс в content stack (управляется через view)
        self._page_index: dict[str, int] = {}

        # Маппинг ключ → индекс в action stack (управляется через view)
        self._action_page_index: dict[str, int] = {}

        # Ленивые панели администрации: ключ → None (не создана) или виджет
        self._lazy_admin_panels: dict[str, object | None] = {}

    # ------------------------------------------------------------------
    # Реестр секций
    # ------------------------------------------------------------------

    def register_section(self, section: SectionProtocol) -> None:
        """Зарегистрировать секцию в реестре презентера."""
        self._sections[section.key] = section
        logger.debug("Секция зарегистрирована: %s (%s)", section.key, section.title)

    # ------------------------------------------------------------------
    # Регистрация admin-панелей (ленивые)
    # ------------------------------------------------------------------

    def register_lazy_admin_panel(self, key: str) -> None:
        """Объявить ключ как ленивую панель администрации."""
        self._lazy_admin_panels[key] = None

    def notify_admin_panel_created(self, key: str, widget: object, action_idx: int, content_idx: int) -> None:
        """Уведомить презентер о создании admin-панели и сохранить индексы."""
        self._lazy_admin_panels[key] = widget
        self._page_index[key] = content_idx
        self._action_page_index[key] = action_idx

    def is_lazy_admin_panel(self, key: str) -> bool:
        """Является ли ключ ленивой панелью (ещё не созданной)."""
        return key in self._lazy_admin_panels and key not in self._page_index

    # ------------------------------------------------------------------
    # Регистрация страниц (вызывается из tab.py при построении UI)
    # ------------------------------------------------------------------

    def register_content_page(self, key: str, index: int) -> None:
        """Сохранить индекс страницы content stack для ключа."""
        self._page_index[key] = index

    def register_action_page(self, key: str, index: int) -> None:
        """Сохранить индекс страницы action stack для ключа."""
        self._action_page_index[key] = index

    # ------------------------------------------------------------------
    # Навигация
    # ------------------------------------------------------------------

    def on_tree_item_changed(self, key: str) -> None:
        """Обработать смену активного элемента дерева навигации.

        Логика:
        1. Если это ленивая admin-панель — сигнализировать tab о необходимости создания
           (tab создаёт виджет и уведомляет presenter через notify_admin_panel_created)
        2. Переключить content stack
        3. Переключить action stack
        4. Вызвать on_activated / on_deactivated для SectionProtocol-секций
        """
        if not key:
            return

        # Деактивировать предыдущую секцию
        if self._current_key and self._current_key in self._sections:
            try:
                self._sections[self._current_key].on_deactivated()
            except Exception:
                logger.exception("Ошибка on_deactivated для секции %s", self._current_key)

        self._current_key = key

        # Переключить content stack
        idx = self._page_index.get(key)
        if idx is not None:
            self._view.set_content_index(idx)

        # Переключить action stack
        self._switch_action_buttons(key)

        # Активировать новую секцию
        if key in self._sections:
            try:
                self._sections[key].on_activated()
            except Exception:
                logger.exception("Ошибка on_activated для секции %s", key)

    def navigate_to(self, key: str) -> None:
        """Навигировать к секции: выбрать элемент в дереве (вью обработает событие)."""
        self._view.select_tree_key(key)

    # ------------------------------------------------------------------
    # Action-колонка
    # ------------------------------------------------------------------

    def _switch_action_buttons(self, key: str) -> None:
        """Переключить action stack на страницу текущей секции."""
        empty_idx = self._action_page_index.get("_empty", 0)
        idx = self._action_page_index.get(key, empty_idx)
        self._view.set_action_index(idx)

    # ------------------------------------------------------------------
    # Undo/Redo
    # ------------------------------------------------------------------

    def on_bus_change(self) -> None:
        """Обновить состояние кнопок Undo/Redo по текущему ActionBus."""
        self._refresh_undo_redo()

    def _refresh_undo_redo(self) -> None:
        """Прочитать can_undo/can_redo из ActionBus и обновить view."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        self._view.set_undo_enabled(bus.can_undo())
        self._view.set_redo_enabled(bus.can_redo())

    # ------------------------------------------------------------------
    # Вспомогательные геттеры (для tab.py при необходимости)
    # ------------------------------------------------------------------

    @property
    def current_key(self) -> str | None:
        """Текущий активный ключ секции."""
        return self._current_key

    @property
    def page_index(self) -> dict[str, int]:
        """Маппинг ключ → индекс в content stack (read-only view)."""
        return dict(self._page_index)
