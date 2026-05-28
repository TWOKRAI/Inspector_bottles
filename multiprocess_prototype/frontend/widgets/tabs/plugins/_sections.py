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
- ``action_buttons()`` возвращает кнопку «Тест» (sandbox), если передан
  ``open_sandbox_cb``; для несовместимых плагинов — disabled с tooltip.
- ``bus_change_callback`` обновляет редактор при undo/redo через ActionBus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.frontend.forms import RegisterView

from .detail_panels import PluginInfoCard
from .presenter import PluginsPresenter

if TYPE_CHECKING:
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

    def __init__(self, services: AppServices, plugin_manager: Any = None) -> None:
        self._services = services
        self._plugin_manager = plugin_manager
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

            self._widget = PathsSubtabWidget(PluginsPresenter(self._services, plugin_manager=self._plugin_manager))
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
    """Секция одного плагина: RegisterView или PluginInfoCard в content.

    Args:
        services: AppServices — DI-контейнер приложения.
        plugin_name: имя плагина (ключ в registry).
        title: отображаемый заголовок в дереве.
        open_sandbox_cb: callback для открытия sandbox-виджета в content-панели.
            Сигнатура: ``(plugin_name: str, sandbox_widget: QWidget) -> None``.
            Если None — кнопка «Тест» disabled с tooltip «sandbox недоступен».
    """

    def __init__(
        self,
        services: AppServices,
        plugin_name: str,
        title: str,
        open_sandbox_cb: "Callable[[str, QWidget], None] | None" = None,
        registers_manager: Any = None,
    ) -> None:
        self._services = services
        self._key = plugin_name
        self._title = title
        self._widget: QWidget | None = None
        self._register_view: RegisterView | None = None
        # G.2: live RegistersManager (FieldInfo для RegisterView) — runtime-dep (Q-F1=B).
        self._registers_manager = registers_manager
        # Callback для открытия sandbox (передаётся из PluginsTab)
        self._open_sandbox_cb = open_sandbox_cb
        # Singleton sandbox-виджет для этой секции (создаётся при первом клике)
        self._sandbox_widget: QWidget | None = None

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
        """Вернуть кнопку «Тест» для запуска sandbox.

        Если open_sandbox_cb не задан — кнопка disabled с tooltip.
        Если плагин несовместим с sandbox — кнопка disabled с причиной.
        Если плагин совместим — кнопка enabled, клик открывает sandbox.
        """
        btn = QPushButton("Тест")

        if self._open_sandbox_cb is None:
            # Обратная совместимость: таб без sandbox-поддержки
            btn.setEnabled(False)
            btn.setToolTip("sandbox недоступен")
            return [btn]

        # Проверяем совместимость плагина с sandbox
        from .sandbox_presenter import SandboxPresenter

        compat = SandboxPresenter(self._services).check_compatibility(self._key)
        if not compat.ok:
            btn.setEnabled(False)
            btn.setToolTip(compat.reason)
        else:
            btn.clicked.connect(self._on_test_clicked)

        return [btn]

    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...

    # -------- Sandbox --------

    def _on_test_clicked(self) -> None:
        """Открыть sandbox-виджет для этого плагина.

        Создаёт PluginSandboxWidget один раз (singleton per section).
        При повторном клике — просто переключает на уже созданный виджет.
        """
        if self._open_sandbox_cb is None:
            return

        if self._sandbox_widget is None:
            from .sandbox import PluginSandboxWidget
            from .sandbox_presenter import SandboxPresenter

            presenter = SandboxPresenter(self._services)
            self._sandbox_widget = PluginSandboxWidget(
                presenter=presenter,
                plugin_name=self._key,
                services=self._services,
            )

        self._open_sandbox_cb(self._key, self._sandbox_widget)

    # -------- SectionWithEvents (bus подписка через BaseTreeNavTab) --------

    def bus_change_callback(self) -> Callable[[], None] | None:
        """Callback для подписки на ActionBus — обновлять editor при undo/redo."""
        return self._on_bus_changed

    # -------- Internal --------

    def _build_widget(self) -> None:
        presenter = PluginsPresenter(self._services, registers_manager=self._registers_manager)
        info = presenter.get_plugin_info(self._key)

        if info.get("has_registers"):
            fields = presenter.get_register_fields(self._key)
            if fields:
                # TODO Phase G (G.4): form_context не покрыт AppServices Protocol'ами.
                view = RegisterView(fields, form_ctx=None)
                view.field_changed.connect(self._on_field_changed)
                self._register_view = view

                from multiprocess_prototype.frontend.widgets.access import (
                    bind_edit_permission,
                )

                # Permission gating через AuthFacade Protocol (F.6).
                bind_edit_permission(
                    view,
                    "tabs.plugins.edit",
                    self._services.auth,
                )
                self._widget = view
                return

        # Fallback — информационная карточка.
        self._widget = PluginInfoCard(info)

    def _get_bus(self) -> Any:
        """ActionBus через services.commands bridge (TODO Phase G (G.4): domain commands)."""
        accessor = getattr(self._services.commands, "action_bus", None)
        return accessor() if callable(accessor) else None

    def _on_field_changed(
        self,
        register_name: str,
        field_name: str,
        old_value: object,
        new_value: object,
    ) -> None:
        """Изменение параметра плагина → ActionBus.execute(field_set)."""
        bus = self._get_bus()
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
        bus = self._get_bus()
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


# BaseTreeNavTab вызывает factory(ctx_arg) с self._ctx (= None после миграции).
# Фабрики игнорируют ctx_arg и замыкают services (паттерн Settings _make_factory).


def _make_category_factory(category_title: str) -> Callable[[object], _CategoryPlaceholder]:
    def factory(_ctx_arg: object) -> _CategoryPlaceholder:
        return _CategoryPlaceholder(
            key=_cat_key(category_title),
            title=category_title,
            text=f"Категория «{category_title}» — выберите плагин из списка.",
        )

    return factory


def _make_plugin_factory(
    services: AppServices,
    plugin_name: str,
    title: str,
    open_sandbox_cb: "Callable[[str, QWidget], None] | None" = None,
    registers_manager: Any = None,
) -> "Callable[[object], _PluginSection]":
    def factory(_ctx_arg: object) -> _PluginSection:
        return _PluginSection(
            services,
            plugin_name,
            title,
            open_sandbox_cb=open_sandbox_cb,
            registers_manager=registers_manager,
        )

    return factory


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------


# Модульный кэш singleton-секций «Пути» по id(services).
# Замыкание в _make_paths_factory не работает между вызовами
# build_plugin_sections() — каждый refresh_catalog() создавал бы новую секцию
# с новым PathsSubtabWidget, что ломало бы подписку catalog_updated.
_PATHS_SECTION_CACHE: "dict[int, _PathsSection]" = {}


def _make_paths_factory(
    services: AppServices,
    plugin_manager: Any = None,
) -> "Callable[[object], _PathsSection]":
    """Фабрика singleton-секции «Пути».

    Кэш по id(services) переживает повторные вызовы build_plugin_sections(),
    что гарантирует сохранение подписки catalog_updated после refresh_catalog().
    """
    cache_key = id(services)

    def factory(_ctx_arg: object) -> _PathsSection:
        section = _PATHS_SECTION_CACHE.get(cache_key)
        if section is None:
            section = _PathsSection(services, plugin_manager)
            _PATHS_SECTION_CACHE[cache_key] = section
        return section

    return factory


def build_plugin_sections(
    services: AppServices,
    *,
    plugin_manager: Any = None,
    registers_manager: Any = None,
    open_sandbox_cb: "Callable[[str, QWidget], None] | None" = None,
) -> "list[SectionSpec]":
    """Сформировать декларацию секций PluginsTab.

    Task E.5: принимает AppServices вместо AppContext. plugin_manager —
    runtime-объект вне AppServices (управление путями плагинов).

    Структура:
    1. Корневая секция «Пути» (__paths__) — управление директориями плагинов.
    2. Для каждой уникальной категории — родительский SectionSpec (placeholder).
    3. Под каждой категорией — lazy-секции плагинов.

    Порядок категорий — по сортированному списку из реестра.

    Args:
        services: AppServices — DI-контейнер приложения.
        plugin_manager: PluginManager (discovery/hot-reload) — для секции «Пути».
        registers_manager: live RegistersManager (FieldInfo) — для RegisterView плагин-секций (G.2).
        open_sandbox_cb: callback для открытия sandbox в content-панели.
            Сигнатура: ``(plugin_name: str, sandbox_widget: QWidget) -> None``.
            По умолчанию None — кнопка «Тест» disabled (обратная совместимость).
    """
    presenter = PluginsPresenter(services)
    plugins = presenter.list_plugins()  # [(name, display, category), ...]

    sections: list[SectionSpec] = []

    # Первым добавляем секцию «Пути» (корневой элемент, без parent_key)
    sections.append(
        SectionSpec(
            key=_PATHS_KEY,
            title="Пути",
            factory=_make_paths_factory(services, plugin_manager),
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
                    factory=_make_plugin_factory(
                        services,
                        plugin_name,
                        plugin_title,
                        open_sandbox_cb,
                        registers_manager=registers_manager,
                    ),
                    parent_key=cat_section_key,
                    lazy=True,
                )
            )

    return sections
