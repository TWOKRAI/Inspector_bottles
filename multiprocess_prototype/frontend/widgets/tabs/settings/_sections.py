# -*- coding: utf-8 -*-
"""Декларация секций для SettingsTab.

Функция ``build_settings_sections`` возвращает список ``SectionSpec[AppContext]``
с 9 секциями (admin_dashboard + 4 admin-панели + system/interface/appearance/history).

Адаптер ``_SectionAdapter`` оборачивает виджеты (AdminDashboard, admin-панели),
которые не реализуют ``SectionProtocol`` полностью.

См. ADR-126, Phase 4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.widgets.tabs.section_protocol import (
        SectionProtocol,
    )
    from multiprocess_prototype.frontend.app_context import AppContext


# ---------------------------------------------------------------------------
# Адаптер для виджетов без полного SectionProtocol
# ---------------------------------------------------------------------------


class _SectionAdapter:
    """Адаптер для виджетов без полного SectionProtocol (AdminDashboard, admin-панели)."""

    def __init__(self, *, key: str, title: str, widget: QWidget) -> None:
        self._key = key
        self._title = title
        self._widget = widget

    @property
    def key(self) -> str:
        """Уникальный идентификатор секции."""
        return self._key

    @property
    def title(self) -> str:
        """Отображаемое название секции."""
        return self._title

    def widget(self) -> QWidget:
        """Корневой QWidget секции."""
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        """Кнопки для action-колонки (если доступны на виджете)."""
        get_buttons = getattr(self._widget, "action_buttons", None)
        if callable(get_buttons):
            return get_buttons()
        return []

    def on_activated(self) -> None:
        """Вызвать on_activated у виджета, если метод есть."""
        on_act = getattr(self._widget, "on_activated", None)
        if callable(on_act):
            on_act()

    def on_deactivated(self) -> None:
        """Вызвать on_deactivated у виджета, если метод есть."""
        on_deact = getattr(self._widget, "on_deactivated", None)
        if callable(on_deact):
            on_deact()


# ---------------------------------------------------------------------------
# Фабрики секций
# ---------------------------------------------------------------------------


def _admin_dashboard_factory(ctx: "AppContext") -> _SectionAdapter:
    """Фабрика AdminDashboard — обзорная панель администрации."""
    from .administration.dashboard import AdminDashboard

    auth = ctx.auth
    auth_state = auth.state if auth is not None else None
    widget = AdminDashboard(auth_state)
    return _SectionAdapter(key="admin_dashboard", title="Администрация", widget=widget)


def _users_factory(ctx: "AppContext") -> _SectionAdapter:
    """Фабрика UsersPanel (ленивая)."""
    from .administration.users_panel import UsersPanel

    widget = UsersPanel(ctx.auth)
    return _SectionAdapter(key="users", title="Пользователи", widget=widget)


def _roles_factory(ctx: "AppContext") -> _SectionAdapter:
    """Фабрика RolesPanel (ленивая)."""
    from .administration.roles_panel import RolesPanel

    widget = RolesPanel(ctx.auth, ctx.action_bus())
    return _SectionAdapter(key="roles", title="Роли", widget=widget)


def _sessions_factory(ctx: "AppContext") -> _SectionAdapter:
    """Фабрика SessionsPanel (ленивая)."""
    from .administration.sessions_panel import SessionsPanel

    widget = SessionsPanel(ctx.auth)
    return _SectionAdapter(key="sessions", title="Сессии", widget=widget)


def _audit_log_factory(ctx: "AppContext") -> _SectionAdapter:
    """Фабрика AuditLogPanel (ленивая)."""
    from .administration.audit_log_panel import AuditLogPanel

    widget = AuditLogPanel(ctx.auth)
    return _SectionAdapter(key="audit_log", title="Audit log", widget=widget)


def _system_factory(ctx: "AppContext") -> "SectionProtocol":
    """Фабрика SystemSection — системные настройки."""
    from .system import SystemSection

    return SystemSection(ctx)


def _system_presenter_factory(ctx: "AppContext", section: object) -> object:
    """Фабрика SystemSettingsPresenter для инжекта через set_presenter."""
    from .system.presenter import SystemSettingsPresenter

    return SystemSettingsPresenter(view=section, rm=None, ui=None, ctx=ctx)


def _interface_factory(ctx: "AppContext") -> "SectionProtocol":
    """Фабрика InterfaceSection — настройки интерфейса."""
    from .interface import InterfaceSection

    return InterfaceSection(ctx)


def _appearance_factory(ctx: "AppContext") -> "SectionProtocol":
    """Фабрика AppearanceSection — оформление (не принимает ctx)."""
    from .appearance import AppearanceSection

    return AppearanceSection()


def _appearance_presenter_factory(ctx: "AppContext", section: object) -> object:
    """Фабрика AppearancePresenter — создаёт theme_manager и presets_manager."""
    from multiprocess_prototype.frontend.styles.theme_loader import create_theme_manager
    from multiprocess_prototype.frontend.managers.theme_presets_manager import (
        ThemePresetsManager,
    )
    from .appearance.presenter import AppearancePresenter

    return AppearancePresenter(
        view=section,
        theme_manager=create_theme_manager(),
        presets_manager=ThemePresetsManager(),
    )


def _history_factory(ctx: "AppContext") -> "SectionProtocol":
    """Фабрика HistorySection — история действий."""
    from .history import HistorySection

    return HistorySection(ctx)


def _history_presenter_factory(ctx: "AppContext", section: object) -> object:
    """Фабрика HistoryPresenter для инжекта через set_presenter."""
    from .history.presenter import HistoryPresenter

    return HistoryPresenter(view=section, rm=None, ui=None, ctx=ctx)


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


def build_settings_sections(ctx: "AppContext") -> "list[SectionSpec[AppContext]]":
    """Вернуть список SectionSpec для SettingsTab.

    Порядок секций зафиксирован baseline-phase2.md:
    1. admin_dashboard (раскрывающаяся ветка) → users / roles / sessions / audit_log
    2. system_settings (активный по умолчанию)
    3. interface_settings
    4. appearance
    5. history
    """
    return [
        # --- Администрация ---
        SectionSpec(
            key="admin_dashboard",
            title="Администрация",
            factory=_admin_dashboard_factory,
        ),
        SectionSpec(
            key="users",
            title="Пользователи",
            factory=_users_factory,
            parent_key="admin_dashboard",
            lazy=True,
        ),
        SectionSpec(
            key="roles",
            title="Роли",
            factory=_roles_factory,
            parent_key="admin_dashboard",
            lazy=True,
        ),
        SectionSpec(
            key="sessions",
            title="Сессии",
            factory=_sessions_factory,
            parent_key="admin_dashboard",
            lazy=True,
        ),
        SectionSpec(
            key="audit_log",
            title="Audit log",
            factory=_audit_log_factory,
            parent_key="admin_dashboard",
            lazy=True,
        ),
        # --- Top-level секции ---
        SectionSpec(
            key="system_settings",
            title="Настройки системы",
            factory=_system_factory,
            presenter_factory=_system_presenter_factory,
        ),
        SectionSpec(
            key="interface_settings",
            title="Настройка интерфейса",
            factory=_interface_factory,
        ),
        SectionSpec(
            key="appearance",
            title="Оформление",
            factory=_appearance_factory,
            presenter_factory=_appearance_presenter_factory,
        ),
        SectionSpec(
            key="history",
            title="История",
            factory=_history_factory,
            presenter_factory=_history_presenter_factory,
        ),
    ]
