# -*- coding: utf-8 -*-
"""Декларация секций для SettingsTab.

Функция ``build_settings_sections`` возвращает список ``SectionSpec``
с 9 секциями (admin_dashboard + 4 admin-панели + system/interface/appearance/history).

Адаптер ``_SectionAdapter`` оборачивает виджеты (AdminDashboard, admin-панели),
которые не реализуют ``SectionProtocol`` полностью.

Task D.5: переход на AppServices. Принимает AppServices + auth_ctx (AuthContext).
auth_ctx передаётся отдельно, так как AuthContext имеет поля manager/state/audit,
выходящие за рамки минимального AuthFacade Protocol. Phase E расширит AuthFacade
или введёт AdminAuthContext Protocol.

TODO (Phase E): заменить auth_ctx на расширенный AuthFacade Protocol,
чтобы полностью убрать зависимость от AuthContext в _sections.

См. ADR-126, Phase 4, Task D.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.domain.app_services import AppServices

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.widgets.tabs.section_protocol import (
        SectionProtocol,
    )
    from multiprocess_prototype.frontend.auth_context import AuthContext


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
# Фабрики секций — принимают (services, auth_ctx)
# ---------------------------------------------------------------------------


def _admin_dashboard_factory(services: AppServices, auth_ctx: "AuthContext | None") -> _SectionAdapter:
    """Фабрика AdminDashboard — обзорная панель администрации."""
    from .administration.dashboard import AdminDashboard

    auth_state = auth_ctx.state if auth_ctx is not None else None
    widget = AdminDashboard(auth_state)
    return _SectionAdapter(key="admin_dashboard", title="Администрация", widget=widget)


def _users_factory(services: AppServices, auth_ctx: "AuthContext | None") -> _SectionAdapter:
    """Фабрика UsersPanel (ленивая)."""
    from .administration.users_panel import UsersPanel

    widget = UsersPanel(auth_ctx)
    return _SectionAdapter(key="users", title="Пользователи", widget=widget)


def _roles_factory(services: AppServices, auth_ctx: "AuthContext | None") -> _SectionAdapter:
    """Фабрика RolesPanel (ленивая).

    ActionBus берётся из services.commands если поддерживает action_bus().
    TODO (Phase E): расширить CommandDispatcher Protocol методом action_bus().
    """
    from .administration.roles_panel import RolesPanel

    bus = getattr(services.commands, "action_bus", None)
    if callable(bus):
        bus = bus()

    widget = RolesPanel(auth_ctx, bus)
    return _SectionAdapter(key="roles", title="Роли", widget=widget)


def _sessions_factory(services: AppServices, auth_ctx: "AuthContext | None") -> _SectionAdapter:
    """Фабрика SessionsPanel (ленивая)."""
    from .administration.sessions_panel import SessionsPanel

    widget = SessionsPanel(auth_ctx)
    return _SectionAdapter(key="sessions", title="Сессии", widget=widget)


def _audit_log_factory(services: AppServices, auth_ctx: "AuthContext | None") -> _SectionAdapter:
    """Фабрика AuditLogPanel (ленивая)."""
    from .administration.audit_log_panel import AuditLogPanel

    widget = AuditLogPanel(auth_ctx)
    return _SectionAdapter(key="audit_log", title="Audit log", widget=widget)


def _system_factory(services: AppServices, auth_ctx: "AuthContext | None") -> "SectionProtocol":
    """Фабрика SystemSection — системные настройки.

    SystemSection получает services для доступа к config и commands.
    """
    from .system import SystemSection

    return SystemSection(services=services)


def _system_presenter_factory(services: AppServices, auth_ctx: "AuthContext | None", section: object) -> object:
    """Фабрика SystemSettingsPresenter для инжекта через set_presenter."""
    from .system.presenter import SystemSettingsPresenter

    return SystemSettingsPresenter(view=section, rm=None, ui=None, services=services)


def _interface_factory(services: AppServices, auth_ctx: "AuthContext | None") -> "SectionProtocol":
    """Фабрика InterfaceSection — настройки интерфейса.

    InterfaceSection использует process._restart_ui — нет в AppServices Protocol.
    TODO (Phase E): добавить ProcessControl Protocol в AppServices или оставить
    как separate dependency injection.
    Для D.5 передаём None как AppContext fallback — InterfaceSection работает
    без ctx (кнопка «Обновить UI» не функциональна, но не падает).
    """
    from .interface import InterfaceSection

    return InterfaceSection(ctx=None)  # type: ignore[arg-type]


def _appearance_factory(services: AppServices, auth_ctx: "AuthContext | None") -> "SectionProtocol":
    """Фабрика AppearanceSection — оформление (не принимает зависимости)."""
    from .appearance import AppearanceSection

    return AppearanceSection()


def _appearance_presenter_factory(services: AppServices, auth_ctx: "AuthContext | None", section: object) -> object:
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


def _history_factory(services: AppServices, auth_ctx: "AuthContext | None") -> "SectionProtocol":
    """Фабрика HistorySection — история действий."""
    from .history import HistorySection

    return HistorySection(services=services)


def _history_presenter_factory(services: AppServices, auth_ctx: "AuthContext | None", section: object) -> object:
    """Фабрика HistoryPresenter для инжекта через set_presenter."""
    from .history.presenter import HistoryPresenter

    return HistoryPresenter(view=section, rm=None, ui=None, services=services)


# ---------------------------------------------------------------------------
# Обёртки-адаптеры для SectionSpec (который ожидает factory(ctx) сигнатуру)
# ---------------------------------------------------------------------------
# BaseTreeNavTab передаёт `ctx` в фабрики через SectionSpec. После Task D.5
# SettingsTab передаёт ctx=None — нам нужно замкнуть (services, auth_ctx) в
# замыканиях, совместимых с сигнатурой SectionSpec factory(ctx_arg).


def _make_factory(fn, services: AppServices, auth_ctx: "AuthContext | None"):
    """Создать lambda-фабрику из (services, auth_ctx) → сигнатура factory(ctx_arg)."""
    return lambda _ctx_arg: fn(services, auth_ctx)


def _make_presenter_factory(fn, services: AppServices, auth_ctx: "AuthContext | None"):
    """Создать lambda presenter-фабрику → сигнатура factory(ctx_arg, section)."""
    return lambda _ctx_arg, section: fn(services, auth_ctx, section)


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


def build_settings_sections(
    services: AppServices,
    *,
    auth_ctx: "AuthContext | None" = None,
) -> "list[SectionSpec]":
    """Вернуть список SectionSpec для SettingsTab.

    Task D.5: принимает AppServices + auth_ctx вместо AppContext.

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
            factory=_make_factory(_admin_dashboard_factory, services, auth_ctx),
        ),
        SectionSpec(
            key="users",
            title="Пользователи",
            factory=_make_factory(_users_factory, services, auth_ctx),
            parent_key="admin_dashboard",
            lazy=True,
        ),
        SectionSpec(
            key="roles",
            title="Роли",
            factory=_make_factory(_roles_factory, services, auth_ctx),
            parent_key="admin_dashboard",
            lazy=True,
        ),
        SectionSpec(
            key="sessions",
            title="Сессии",
            factory=_make_factory(_sessions_factory, services, auth_ctx),
            parent_key="admin_dashboard",
            lazy=True,
        ),
        SectionSpec(
            key="audit_log",
            title="Audit log",
            factory=_make_factory(_audit_log_factory, services, auth_ctx),
            parent_key="admin_dashboard",
            lazy=True,
        ),
        # --- Top-level секции ---
        SectionSpec(
            key="system_settings",
            title="Настройки системы",
            factory=_make_factory(_system_factory, services, auth_ctx),
            presenter_factory=_make_presenter_factory(_system_presenter_factory, services, auth_ctx),
        ),
        SectionSpec(
            key="interface_settings",
            title="Настройка интерфейса",
            factory=_make_factory(_interface_factory, services, auth_ctx),
        ),
        SectionSpec(
            key="appearance",
            title="Оформление",
            factory=_make_factory(_appearance_factory, services, auth_ctx),
            presenter_factory=_make_presenter_factory(_appearance_presenter_factory, services, auth_ctx),
        ),
        SectionSpec(
            key="history",
            title="История",
            factory=_make_factory(_history_factory, services, auth_ctx),
            presenter_factory=_make_presenter_factory(_history_presenter_factory, services, auth_ctx),
        ),
    ]
