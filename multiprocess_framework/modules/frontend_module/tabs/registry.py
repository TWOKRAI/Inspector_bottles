# -*- coding: utf-8 -*-
"""TabRegistry — generic-механизм вкладок приложения (NEW-D1).

Перенесён из прототипа (``multiprocess_prototype/frontend/tab_factory.py``):
это чистая механика, не привязанная к конкретным вкладкам приложения.

Реестр умеет:
- строить вкладки из ``Sequence[TabSpec]`` в порядке списка;
- ленивую инстанциацию содержимого (``LazyTab``) — по умолчанию;
- заглушку для вкладок без фабрики (через инъектируемый ``placeholder_factory``);
- фильтрацию видимости по ``view_permission`` относительно текущего
  ``AccessContext`` и пере-применение при смене контекста (login/logout/роль).

Границы: 0 обратных импортов в прикладной слой. Реестр НЕ знает конкретных
вкладок, типов сервисов/runtime приложения (форвардит их как opaque
``factory_context``), ни реализации источника прав (контракт
``AccessContextSource``). Всё прикладное собирается в composition root.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional, Protocol, Sequence, Tuple

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QTabWidget,
    QWidget,
)

from .lazy_tab import LazyTab
from .spec import TabSpec

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.managers.access_context import (
        AccessContext,
    )

logger = logging.getLogger(__name__)


class AccessContextSource(Protocol):
    """Контракт источника прав для фильтрации вкладок.

    Прикладной ``AuthState`` (или тестовый stub) удовлетворяет его: несёт
    актуальный ``AccessContext`` и Qt-сигнал его смены. Реестр только читает
    ``access_context`` и подписывается на ``access_context_changed`` — он не
    зависит от конкретной реализации auth-слоя.
    """

    # Актуальный контекст прав; должен иметь метод has_permission(name) -> bool.
    access_context: "AccessContext"
    # Qt-сигнал: испускается при login/logout/смене роли. Реестр .connect(...).
    access_context_changed: object


# Фабрика-заглушка: строит виджет для вкладки без собственной фабрики.
PlaceholderFactory = Callable[[TabSpec], QWidget]


class TabRegistry:
    """Реестр вкладок: строит, лениво инстанцирует и фильтрует по правам.

    Args:
        specs: описания вкладок в порядке отображения.
        factory_context: кортеж позиционных аргументов, который форвардится
            фабрике каждой вкладки как ``spec.factory(*factory_context)``.
            Реестр его не интерпретирует (например ``(app_services, runtime)``).
        access_source: источник прав (``AccessContextSource``) для фильтрации.
            ``None`` → все вкладки видимы (legacy/тесты без RBAC).
        placeholder_factory: фабрика заглушки для вкладок без ``factory`` (и как
            fallback при ошибке фабрики). ``None`` → пустой ``QWidget``.
        lazy: ``True`` (по умолчанию) — вкладки с фабрикой оборачиваются в
            ``LazyTab`` (создание при первом показе). ``False`` — немедленно.
    """

    def __init__(
        self,
        specs: Sequence[TabSpec],
        *,
        factory_context: Tuple[object, ...] = (),
        access_source: Optional[AccessContextSource] = None,
        placeholder_factory: Optional[PlaceholderFactory] = None,
        lazy: bool = True,
    ) -> None:
        self._specs: list[TabSpec] = list(specs)
        self._factory_context = tuple(factory_context)
        self._access_source = access_source
        self._placeholder_factory = placeholder_factory
        self._lazy = lazy
        self._tab_widget: Optional[QTabWidget] = None
        # tab_id → индекс в QTabWidget (в порядке specs)
        self._tab_index: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Построение
    # ------------------------------------------------------------------

    def create_tabs(self, tab_widget: QTabWidget) -> None:
        """Создать все вкладки согласно ``specs`` и добавить в ``tab_widget``.

        После построения применяется фильтрация по правам и регистрируется
        подписка на смену ``AccessContext``.
        """
        self._tab_widget = tab_widget
        self._tab_index = {}

        ctx = self._factory_context
        for spec in self._specs:
            if spec.factory is not None:
                if self._lazy:
                    factory = spec.factory
                    widget: QWidget = LazyTab(lambda f=factory: f(*ctx))
                else:
                    widget = self._build_now(spec)
            else:
                widget = self._make_placeholder(spec)

            index = tab_widget.addTab(widget, spec.title)
            self._tab_index[spec.id] = index

        self._apply_permissions()
        self._wire_access_source()

    def create_tab(self, tab_id: str) -> Optional[QWidget]:
        """Создать одну вкладку по id (без ленивой обёртки).

        Неизвестный id → ``None``. Ошибка фабрики или возврат ``None`` →
        заглушка.
        """
        spec = next((s for s in self._specs if s.id == tab_id), None)
        if spec is None:
            return None
        if spec.factory is not None:
            return self._build_now(spec)
        return self._make_placeholder(spec)

    def _build_now(self, spec: TabSpec) -> QWidget:
        """Немедленно вызвать фабрику вкладки; fallback на заглушку."""
        assert spec.factory is not None
        try:
            result = spec.factory(*self._factory_context)
            return result if result is not None else self._make_placeholder(spec)
        except Exception:
            logger.exception("Ошибка создания вкладки %s", spec.id)
            return self._make_placeholder(spec)

    def _make_placeholder(self, spec: TabSpec) -> QWidget:
        """Построить заглушку через инъектируемую фабрику (или пустой QWidget)."""
        if self._placeholder_factory is not None:
            return self._placeholder_factory(spec)
        return QWidget()

    # ------------------------------------------------------------------
    # Права
    # ------------------------------------------------------------------

    def _wire_access_source(self) -> None:
        """Подписаться на смену AccessContext (если источник задан)."""
        if self._access_source is None:
            return
        self._access_source.access_context_changed.connect(  # type: ignore[attr-defined]
            self._on_access_context_changed
        )

    def _on_access_context_changed(self, _ctx: object) -> None:
        """Слот смены контекста — пере-применить видимость вкладок."""
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        """Скрыть/показать вкладки по ``view_permission`` текущего контекста.

        ``access_source is None`` → все вкладки видимы (legacy без RBAC).
        """
        if self._tab_widget is None or self._access_source is None:
            return

        ctx = self._access_source.access_context
        bar = self._tab_widget.tabBar()
        visible_count = 0
        for spec in self._specs:
            index = self._tab_index.get(spec.id)
            if index is None:
                continue
            visible = spec.view_permission is None or ctx.has_permission(spec.view_permission)
            bar.setTabVisible(index, visible)
            if visible:
                visible_count += 1

        if visible_count == 0:
            logger.warning(
                "TabRegistry: ВСЕ вкладки скрыты — у текущего пользователя нет ни "
                "одного tabs.*.view. role_name=%r, permissions=%s",
                getattr(ctx, "role_name", "?"),
                sorted(getattr(ctx, "permissions", ())),
            )
