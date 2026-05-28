"""TabFactory — фабрика табов с ленивой инициализацией, фильтрацией по permissions и заглушками.

Использование:
    factory = TabFactory(ctx, custom_factories=register_all_tabs())
    factory.create_tabs(tab_widget)

custom_factories: dict[tab_id -> Callable[[AppServices, RuntimeDeps], QWidget]]
    Если id отсутствует — создаётся PlaceholderTab.

Task F.9: фабрики принимают (AppServices, RuntimeDeps) вместо AppContext.
TabFactory по-прежнему хранит ctx для permission-фильтрации (ctx.auth.state),
но при вызове фабрик собирает RuntimeDeps из ctx и передаёт services + runtime.

Фильтрация по permissions:
    После создания всех табов фабрика читает `ctx.auth.state.access_context`
    и скрывает табы, у которых `view_permission` не выдан текущему пользователю
    (через `QTabBar.setTabVisible`). Подписывается на `access_context_changed`
    и пере-применяет видимость при login/logout/смене роли.

    Если в AppContext нет `auth_state` — все табы видимы (legacy-режим).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .runtime_deps import RuntimeDeps
from .widgets.tabs.placeholder import PlaceholderTab

if TYPE_CHECKING:
    from .app_context import AppContext
    from multiprocess_framework.modules.frontend_module.managers.access_context import (
        AccessContext,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Порядок и метаданные всех табов приложения
# ---------------------------------------------------------------------------
#
# Поля:
#   id, title, description — отображение.
#   view_permission — имя permission (`tabs.<id>.view`). Если у текущего
#     `AccessContext` его нет — таб скрыт через QTabBar.setTabVisible.
#     None означает «доступен всем» (например, для гостевых табов до login).

TAB_ORDER: list[dict] = [
    {
        "id": "settings",
        "title": "Settings",
        "description": "Администрирование, конфиг системы",
        "view_permission": "tabs.settings.view",
    },
    {
        "id": "recipes",
        "title": "Recipes",
        "description": "Пресеты/рецепты обработки",
        "view_permission": "tabs.recipes.view",
    },
    {
        "id": "processes",
        "title": "Processes",
        "description": "Управление процессами",
        "view_permission": "tabs.processes.view",
    },
    {
        "id": "services",
        "title": "Services",
        "description": "Камеры SDK, БД, робот, нейронки",
        "view_permission": "tabs.services.view",
    },
    {
        "id": "plugins",
        "title": "Plugins",
        "description": "Обработка изображений, мосты",
        "view_permission": "tabs.plugins.view",
    },
    {
        "id": "pipeline",
        "title": "Pipeline",
        "description": "Визуальный конструктор цепочек",
        "view_permission": "tabs.pipeline.view",
    },
    {
        "id": "displays",
        "title": "Displays",
        "description": "Управление экранами вывода",
        "view_permission": "tabs.displays.view",
    },
]


# ---------------------------------------------------------------------------
# LazyTabWidget — обёртка для ленивой инициализации
# ---------------------------------------------------------------------------


class LazyTabWidget(QWidget):
    """Обёртка для ленивой инициализации таба.

    Содержимое создаётся при первом событии showEvent.
    До этого показывает метку "Loading...".
    """

    def __init__(
        self,
        factory_fn: Callable[[], QWidget],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory_fn = factory_fn
        self._initialized = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Временная метка до первого показа
        self._loading_label = QLabel("Loading...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._loading_label)

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Инициализировать содержимое при первом показе."""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            self._loading_label.deleteLater()
            self._loading_label = None  # type: ignore[assignment]
            try:
                widget = self._factory_fn()
                if widget is not None:
                    self._layout.addWidget(widget)
            except Exception:
                logger.exception("Ошибка создания таба")
                # Fallback — показываем метку об ошибке
                err_label = QLabel("Ошибка загрузки")
                err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._layout.addWidget(err_label)


# ---------------------------------------------------------------------------
# TabFactory
# ---------------------------------------------------------------------------


class TabFactory:
    """Фабрика табов с поддержкой custom factories, ленивой инициализации и permissions.

    Args:
        ctx: AppContext — используется для permission-фильтрации (ctx.auth.state)
            и сборки RuntimeDeps. Если `ctx.auth` не None — фабрика подписывается
            на `access_context_changed` и применяет видимость табов по
            `view_permission` каждой записи `TAB_ORDER`.
        custom_factories: опциональный dict[tab_id -> factory(services, runtime) -> QWidget]
            Task F.9: фабрики принимают (AppServices, RuntimeDeps), не AppContext.
            Если передан factory для tab_id, таб создаётся через LazyTabWidget.
            Иначе используется PlaceholderTab.
    """

    def __init__(
        self,
        ctx: "AppContext",
        custom_factories: dict[str, Callable] | None = None,
    ) -> None:
        self._ctx = ctx
        self._custom_factories: dict[str, Callable] = custom_factories or {}
        # Сохраняем целевой QTabWidget для re-apply при смене access_context
        self._tab_widget: QTabWidget | None = None
        # Соответствие tab_id → индекс в QTabWidget (порядок TAB_ORDER)
        self._tab_index: dict[str, int] = {}
        # RuntimeDeps собирается один раз из ctx (Q-F1=B)
        self._runtime = self._build_runtime_deps()

    def create_tabs(self, tab_widget: QTabWidget) -> None:
        """Создать все табы согласно TAB_ORDER и добавить в QTabWidget.

        Табы с custom_factories — LazyTabWidget (создаются при первом показе).
        Остальные — PlaceholderTab (создаются немедленно, они лёгкие).

        После создания применяется фильтрация по permissions и регистрируется
        подписка на смену AccessContext.
        """
        self._tab_widget = tab_widget
        self._tab_index = {}

        services = self._ctx.app_services
        runtime = self._runtime

        for tab_info in TAB_ORDER:
            tab_id = tab_info["id"]
            title = tab_info["title"]

            if tab_id in self._custom_factories:
                # Ленивая инициализация: factory вызывается только при первом show
                factory_fn = self._custom_factories[tab_id]
                widget: QWidget = LazyTabWidget(lambda fn=factory_fn, svc=services, rt=runtime: fn(svc, rt))
            else:
                # Заглушка — создаётся сразу (лёгкий виджет)
                widget = PlaceholderTab(
                    tab_id=tab_id,
                    title=title,
                    description=tab_info.get("description", ""),
                )

            index = tab_widget.addTab(widget, title)
            self._tab_index[tab_id] = index

        # Применяем permissions и подписываемся на изменения AccessContext
        self._apply_permissions()
        self._wire_auth_state()

    def create_tab(self, tab_id: str) -> QWidget | None:
        """Создать один таб по id.

        Если tab_id неизвестен — вернуть None.
        Если custom factory есть — вызвать напрямую (без LazyTabWidget).
        При ошибке factory или возврате None — использовать PlaceholderTab.
        """
        tab_info = next((t for t in TAB_ORDER if t["id"] == tab_id), None)
        if tab_info is None:
            return None

        if tab_id in self._custom_factories:
            try:
                result = self._custom_factories[tab_id](self._ctx.app_services, self._runtime)
                return result if result is not None else self._make_placeholder(tab_info)
            except Exception:
                logger.exception("Ошибка создания таба %s", tab_id)
                return self._make_placeholder(tab_info)

        return self._make_placeholder(tab_info)

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def _wire_auth_state(self) -> None:
        """Подписаться на смену AccessContext в AuthState."""
        _auth = self._ctx.auth if hasattr(self._ctx, "auth") else None
        auth_state = _auth.state if _auth is not None else None
        if auth_state is None:
            return
        # Реагируем на login/logout/смену роли — реалогиниваем видимость
        auth_state.access_context_changed.connect(self._on_access_context_changed)

    def _on_access_context_changed(self, _ctx: "AccessContext") -> None:
        """Сигнал из AuthState — обновить видимость табов."""
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        """Скрыть/показать табы по `view_permission` текущего AccessContext.

        Если в AppContext нет `auth_state` — все табы остаются видимыми
        (legacy-режим, для тестов без RBAC).
        """
        if self._tab_widget is None:
            return

        _auth = self._ctx.auth if hasattr(self._ctx, "auth") else None
        auth_state = _auth.state if _auth is not None else None
        if auth_state is None:
            return

        ctx = auth_state.access_context
        bar = self._tab_widget.tabBar()
        visible_count = 0
        for tab_info in TAB_ORDER:
            tab_id = tab_info["id"]
            index = self._tab_index.get(tab_id)
            if index is None:
                continue
            view_perm = tab_info.get("view_permission")
            visible = view_perm is None or ctx.has_permission(view_perm)
            bar.setTabVisible(index, visible)
            if visible:
                visible_count += 1

        if visible_count == 0:
            logger.warning(
                "TabFactory: ВСЕ табы скрыты — у текущего пользователя нет ни одного "
                "tabs.*.view permission. role_name=%r, permissions=%s",
                ctx.role_name,
                sorted(ctx.permissions),
            )

    @staticmethod
    def _make_placeholder(tab_info: dict) -> PlaceholderTab:
        """Создать PlaceholderTab из метаданных таба."""
        return PlaceholderTab(
            tab_id=tab_info["id"],
            title=tab_info["title"],
            description=tab_info.get("description", ""),
        )

    def _build_runtime_deps(self) -> RuntimeDeps:
        """Собрать RuntimeDeps из AppContext (Q-F1=B).

        Вызывается один раз в __init__. Все runtime-accessor'ы AppContext
        вызываются здесь и замораживаются в frozen dataclass.
        """
        ctx = self._ctx
        return RuntimeDeps(
            command_sender=getattr(ctx, "command_sender", None),
            topology_bridge=ctx.topology_bridge() if hasattr(ctx, "topology_bridge") else None,
            bindings=ctx.bindings() if hasattr(ctx, "bindings") else None,
            plugin_manager=ctx.plugin_manager() if hasattr(ctx, "plugin_manager") else None,
            auth_ctx=ctx.auth if hasattr(ctx, "auth") else None,
        )
