# -*- coding: utf-8 -*-
"""Декларация секций для PluginsTab (BaseTreeNavTab).

Структура (Settings-стиль, дерево по категориям):

    ▾ Источники
        capture
        ...
    ▾ Обработка
        color_mask
        grayscale
        ...
    ▾ Вывод
        ...

Категория — ``_CategoryPlaceholder`` (placeholder-секция без виджетов).
Каждый плагин — ``_PluginSection``:
- ``widget()`` строит лениво ``RegisterView`` (если есть register fields) или
  ``PluginInfoCard`` (иначе);
- ``action_buttons()`` пуст — глобальный тогглер Cards/Table живёт в первой
  колонке таба, а не per-section.
- ``bus_change_callback`` обновляет редактор при undo/redo через ActionBus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.frontend.forms import RegisterView

from .detail_panels import PluginInfoCard
from .presenter import PluginsPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext
    from .paths_subtab import PathsSubtabWidget


_CATEGORY_PREFIX = "__cat__"

# Ключ секции «Пути» (корневой, без parent_key)
_PATHS_KEY = "__paths__"


# ---------------------------------------------------------------------------
# _PathsSection — секция управления директориями поиска плагинов
# ---------------------------------------------------------------------------


class _PathsSection:
    """Секция «Пути» — управление директориями поиска плагинов.

    Singleton виджет (lazy): создаётся один раз при первом вызове widget().
    Это важно для сохранения подписки catalog_updated (Task 2.6).
    """

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx
        self._widget: "PathsSubtabWidget | None" = None

    # -------- SectionProtocol --------

    @property
    def key(self) -> str:
        return _PATHS_KEY

    @property
    def title(self) -> str:
        return "Пути"

    def widget(self) -> QWidget:
        """Лениво создать PathsSubtabWidget (singleton — один и тот же экземпляр)."""
        if self._widget is None:
            from .paths_subtab import PathsSubtabWidget

            self._widget = PathsSubtabWidget(PluginsPresenter(self._ctx))
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...


def _cat_key(category: str) -> str:
    return f"{_CATEGORY_PREFIX}{category}"


# ---------------------------------------------------------------------------
# _PluginSection — реальная плагин-секция с RegisterView/InfoCard
# ---------------------------------------------------------------------------


class _PluginSection:
    """Секция одного плагина: RegisterView или PluginInfoCard в content."""

    def __init__(
        self,
        ctx: "AppContext",
        plugin_name: str,
        title: str,
    ) -> None:
        self._ctx = ctx
        self._key = plugin_name
        self._title = title
        self._widget: QWidget | None = None
        self._register_view: RegisterView | None = None

    # -------- SectionProtocol --------

    @property
    def key(self) -> str:
        return self._key

    @property
    def title(self) -> str:
        return self._title

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build_widget()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...

    # -------- SectionWithEvents (bus подписка через BaseTreeNavTab) --------

    def bus_change_callback(self) -> Callable[[], None] | None:
        """Callback для подписки на ActionBus — обновлять editor при undo/redo."""
        return self._on_bus_changed

    # -------- Internal --------

    def _build_widget(self) -> None:
        presenter = PluginsPresenter(self._ctx)
        info = presenter.get_plugin_info(self._key)

        if info.get("has_registers"):
            fields = presenter.get_register_fields(self._key)
            if fields:
                form_ctx = self._ctx.form_context()
                view = RegisterView(fields, form_ctx=form_ctx)
                view.field_changed.connect(self._on_field_changed)
                self._register_view = view

                from multiprocess_prototype.frontend.widgets.access import (
                    bind_edit_permission,
                )

                _auth = getattr(self._ctx, "auth", None)
                bind_edit_permission(
                    view,
                    "tabs.plugins.edit",
                    _auth.state if _auth is not None else None,
                )
                self._widget = view
                return

        # Fallback — информационная карточка.
        self._widget = PluginInfoCard(info)

    def _on_field_changed(
        self,
        register_name: str,
        field_name: str,
        old_value: object,
        new_value: object,
    ) -> None:
        """Изменение параметра плагина → ActionBus.execute(field_set)."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

        action = V2ActionBuilder.field_set_timed(
            register_name,
            field_name,
            new_value,
            old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.execute(action)

    def _on_bus_changed(self) -> None:
        """Callback от ActionBus — обновить RegisterView при undo/redo."""
        bus = self._ctx.action_bus()
        if bus is None or self._register_view is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        if register_name != self._key:
            return
        value = action.backward_patch.get("value") if event_type == "undo" else action.forward_patch.get("value")
        key = f"{register_name}.{action.field_name}"
        if key in self._register_view.editors():
            self._register_view.set_editor_value(key, value)


# ---------------------------------------------------------------------------
# _CategoryPlaceholder — заглушка-категория с текстом по центру
# ---------------------------------------------------------------------------


class _CategoryPlaceholder:
    """Узел категории в дереве: текстовая метка по центру (без кнопок)."""

    def __init__(self, key: str, title: str, text: str) -> None:
        self._key = key
        self._title = title
        self._text = text
        self._widget: QWidget | None = None

    @property
    def key(self) -> str:
        return self._key

    @property
    def title(self) -> str:
        return self._title

    def widget(self) -> QWidget:
        if self._widget is None:
            w = QWidget()
            layout = QVBoxLayout(w)
            label = QLabel(self._text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("role", "placeholder-italic")
            layout.addWidget(label)
            self._widget = w
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...


# ---------------------------------------------------------------------------
# Фабрики
# ---------------------------------------------------------------------------


def _make_category_factory(category_title: str) -> Callable[["AppContext"], _CategoryPlaceholder]:
    def factory(_ctx: "AppContext") -> _CategoryPlaceholder:
        return _CategoryPlaceholder(
            key=_cat_key(category_title),
            title=category_title,
            text=f"Категория «{category_title}» — выберите плагин из списка.",
        )

    return factory


def _make_plugin_factory(plugin_name: str, title: str) -> Callable[["AppContext"], _PluginSection]:
    def factory(ctx: "AppContext") -> _PluginSection:
        return _PluginSection(ctx, plugin_name, title)

    return factory


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


def _make_paths_factory(ctx: "AppContext") -> "Callable[[AppContext], _PathsSection]":
    """Фабрика singleton-секции «Пути».

    Создаёт _PathsSection один раз и возвращает его при каждом вызове,
    чтобы сохранить подписку catalog_updated даже после refresh_catalog().
    """
    # Singleton секции хранится в замыкании
    _instance: list[_PathsSection] = []

    def factory(_ctx: "AppContext") -> _PathsSection:
        if not _instance:
            _instance.append(_PathsSection(ctx))
        return _instance[0]

    return factory


def build_plugin_sections(ctx: "AppContext") -> "list[SectionSpec[AppContext]]":
    """Сформировать декларацию секций PluginsTab.

    Структура:
    1. Корневая секция «Пути» (__paths__) — управление директориями плагинов.
    2. Для каждой уникальной категории — родительский SectionSpec (placeholder).
    3. Под каждой категорией — lazy-секции плагинов.

    Порядок категорий — по сортированному списку из реестра.
    """
    presenter = PluginsPresenter(ctx)
    plugins = presenter.list_plugins()  # [(name, display, category), ...]

    sections: list[SectionSpec[AppContext]] = []

    # Первым добавляем секцию «Пути» (корневой элемент, без parent_key)
    sections.append(
        SectionSpec(
            key=_PATHS_KEY,
            title="Пути",
            factory=_make_paths_factory(ctx),
        )
    )

    seen_categories: set[str] = set()

    # Группируем по категории, сохраняя порядок появления.
    by_category: dict[str, list[tuple[str, str]]] = {}
    for name, _display, category in plugins:
        cat_title = PluginsPresenter.CATEGORY_TITLES.get(category, category)
        by_category.setdefault(cat_title, []).append((name, name))

    # Категории отсортированы по их Russian-title для стабильного порядка.
    for cat_title in sorted(by_category.keys()):
        cat_section_key = _cat_key(cat_title)
        if cat_section_key not in seen_categories:
            seen_categories.add(cat_section_key)
            sections.append(
                SectionSpec(
                    key=cat_section_key,
                    title=cat_title,
                    factory=_make_category_factory(cat_title),
                )
            )
        for plugin_name, plugin_title in by_category[cat_title]:
            sections.append(
                SectionSpec(
                    key=plugin_name,
                    title=plugin_title,
                    factory=_make_plugin_factory(plugin_name, plugin_title),
                    parent_key=cat_section_key,
                    lazy=True,
                )
            )

    return sections
