"""TabFactory — тонкий прикладной адаптер над generic-механизмом вкладок.

NEW-D1: механизм вкладок (построение, ленивая инстанциация, permission-фильтр)
перенесён во ``frontend_module.tabs`` (``TabRegistry``). Здесь остаётся только
прикладной адаптер, сохраняющий историческую сигнатуру ``TabFactory`` для
back-compat (composition root, тесты):

- заглушка вкладок — прикладной ``PlaceholderTab``;
- источник прав — ``auth_ctx.state`` (``AuthState`` удовлетворяет
  ``AccessContextSource``: ``access_context`` + сигнал ``access_context_changed``);
- метаданные вкладок берутся из единого источника ``TABS`` (``tabs_registry``),
  а фактическая фабрика каждой вкладки — из ``custom_factories`` (историческая
  семантика: нет фабрики → ``PlaceholderTab``).

Реэкспорты для совместимости:
- ``LazyTabWidget`` = ``frontend_module.tabs.LazyTab``;
- ``TAB_ORDER`` — derived из ``TABS`` (list[dict]) для старых читателей.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Callable

from multiprocess_framework.modules.frontend_module.tabs import (
    LazyTab as LazyTabWidget,  # noqa: F401 — back-compat реэкспорт
)
from multiprocess_framework.modules.frontend_module.tabs import TabRegistry, TabSpec

from .runtime_deps import RuntimeDeps
from .tabs_registry import TABS
from .widgets.tabs.placeholder import PlaceholderTab

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTabWidget, QWidget

    from multiprocess_prototype.domain.app_services import AppServices

    from .auth_context import AuthContext


# TAB_ORDER — derived из единого источника TABS (back-compat для старых читателей).
TAB_ORDER: list[dict] = [
    {
        "id": spec.id,
        "title": spec.title,
        "description": spec.description,
        "view_permission": spec.view_permission,
    }
    for spec in TABS
]


def _placeholder_from_spec(spec: TabSpec) -> PlaceholderTab:
    """Прикладная заглушка вкладки из TabSpec."""
    return PlaceholderTab(
        tab_id=spec.id,
        title=spec.title,
        description=spec.description,
    )


class TabFactory:
    """Адаптер: строит вкладки прототипа через ``TabRegistry``.

    Историческая сигнатура сохранена. ``custom_factories`` задаёт фабрику для
    каждого tab_id; отсутствие фабрики → ``PlaceholderTab`` (как раньше).

    Args:
        app_services: DI-контейнер editor-state, форвардится фабрикам вкладок.
        auth_ctx: источник прав. ``auth_ctx.state`` (``AuthState``) используется
            для permission-фильтрации. ``None`` → все вкладки видимы (legacy).
        runtime: runtime-зависимости, второй аргумент фабрик. ``None`` → ``RuntimeDeps()``.
        custom_factories: ``dict[tab_id -> factory(services, runtime) -> QWidget]``.
    """

    def __init__(
        self,
        app_services: "AppServices",
        *,
        auth_ctx: "AuthContext | None" = None,
        runtime: "RuntimeDeps | None" = None,
        custom_factories: dict[str, Callable] | None = None,
    ) -> None:
        self._services = app_services
        self._runtime = runtime if runtime is not None else RuntimeDeps()
        self._auth_ctx = auth_ctx
        factories = custom_factories or {}

        # Метаданные из единого источника TABS, фабрика — из custom_factories.
        specs = [replace(spec, factory=factories.get(spec.id)) for spec in TABS]
        access_source = auth_ctx.state if auth_ctx is not None else None

        self._registry = TabRegistry(
            specs,
            factory_context=(self._services, self._runtime),
            access_source=access_source,
            placeholder_factory=_placeholder_from_spec,
        )

    def create_tabs(self, tab_widget: "QTabWidget") -> None:
        """Создать все вкладки в ``tab_widget`` (делегат в TabRegistry)."""
        self._registry.create_tabs(tab_widget)

    def create_tab(self, tab_id: str) -> "QWidget | None":
        """Создать одну вкладку по id (делегат в TabRegistry)."""
        return self._registry.create_tab(tab_id)
