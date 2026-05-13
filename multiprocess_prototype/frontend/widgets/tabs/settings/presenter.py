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

# ---------------------------------------------------------------------------
# Конфигурация навигации (presenter — единственный владелец)
# ---------------------------------------------------------------------------

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


class SettingsPresenter(TabPresenterBase[SettingsView, None]):
    """Презентер Settings таба.

    Отвечает за:
    - конфигурацию и порядок секций навигации (единственный владелец)
    - навигацию по секциям (tree item → content stack + action stack)
    - ленивое создание панелей администрации (координирует через view)
    - реестр секций (SectionProtocol)
    - undo/redo state (через view)

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
    # Конфигурация навигации (публичные аксессоры для view)
    # ------------------------------------------------------------------

    def admin_children(self) -> list[tuple[str, str]]:
        """Вернуть список (ключ, название) дочерних узлов «Администрация»."""
        return list(_ADMIN_CHILDREN)

    def top_sections(self) -> list[tuple[str, str]]:
        """Вернуть список (ключ, название) top-level секций."""
        return list(_TOP_SECTIONS)

    # ------------------------------------------------------------------
    # Populate — координирует построение навигации через view
    # ------------------------------------------------------------------

    def populate(self) -> None:
        """Заполнить навигацию и content stack, вызывая методы view.

        Presenter знает ЧТО создать (порядок ключей), view знает КАК (Qt-виджеты).
        """
        # Заполнить QTreeWidget через view
        self._view.build_nav_tree(_TOP_SECTIONS, _ADMIN_CHILDREN)

        # Объявить ленивые admin-панели
        for key, _ in _ADMIN_CHILDREN:
            self.register_lazy_admin_panel(key)

        # Добавить страницы контента в строгом порядке через view
        self._view.add_admin_dashboard_page(_ADMIN_CHILDREN)
        self._view.add_system_settings_page()
        self._view.add_interface_settings_page()
        self._view.add_appearance_page()
        self._view.add_history_page()

        # Выбрать начальную секцию
        self.navigate_to("system_settings")

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

    def ensure_admin_panel(self, key: str) -> None:
        """Если панель ещё не создана — попросить view создать и зарегистрировать её.

        View создаёт Qt-виджет и вызывает notify_admin_panel_created()
        для обратной регистрации индексов.
        """
        if self.is_lazy_admin_panel(key):
            self._view.create_admin_panel(key)

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
        1. Если это ленивая admin-панель — попросить view создать (ленивая инициализация)
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

        # Ленивое создание admin-панелей (presenter координирует через view)
        self.ensure_admin_panel(key)

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

    def get_action_index(self, key: str) -> int:
        """Получить индекс action-страницы по ключу (публичный аксессор)."""
        empty_idx = self._action_page_index.get("_empty", 0)
        return self._action_page_index.get(key, empty_idx)

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
    # Вспомогательные геттеры
    # ------------------------------------------------------------------

    @property
    def current_key(self) -> str | None:
        """Текущий активный ключ секции."""
        return self._current_key
