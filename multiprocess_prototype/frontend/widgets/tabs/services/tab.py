# -*- coding: utf-8 -*-
"""ServicesTab — таб управления сервисами по шаблону Settings.

3 колонки + мастер-скролл + QGroupBox-заголовок через ``DiffScrollTabLayout``;
tree-навигация через ``BaseTreeNavTab``. Под родительской веткой «Сервисы»
лежат сервисные секции динамически из ServiceRegistry; top-level
«Нейронные сети» — placeholder для будущих фич. Top-level «Пути» —
управление директориями поиска сервисов.

Каждая сервисная секция держит _ServiceInfoCard в content-колонке и три кнопки
управления (Запустить/Остановить/Перезапуск) в action-колонке.
"""

from __future__ import annotations


from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseTreeNavTab
from multiprocess_framework.modules.frontend_module.widgets.tabs.nav_tree_utils import (
    find_tree_item,
)
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.events import RecipeActivated
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from ._sections import build_services_sections


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с Settings/Recipes/Processes.
    return DiffScrollTabLayout(title="Сервисы", action_width=160, nav_width=230)


class ServicesTab(BaseTreeNavTab):
    """Таб «Сервисы» — BaseTreeNavTab с секциями сервисов и плейсхолдеров.

    Структурно идентичен SettingsTab: tree-nav слева, action-кнопки секции
    в левой колонке, content-виджет секции — в правой; мастер-скролл общий.

    Динамически читает сервисы из ServiceManager (не хардкод).
    Подвкладка «Пути» (__service_paths__) управляет директориями.

    Task E.4: мигрирован на AppServices DI. Принимает ``services: AppServices``.
    """

    def __init__(self, services: AppServices, *, parent: QWidget | None = None) -> None:
        self._services = services
        # G.4.4: undo/redo на domain CommandDispatcher (services.commands
        # удовлетворяет UndoRedoController). Единая глобальная история; кнопки
        # рефрешат enabled-состояние по change-callback после dispatch/undo/redo.
        commands = services.commands
        super().__init__(
            title="Сервисы",
            sections=build_services_sections(services),
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
            layout_factory=_layout_factory,
            bus_change_subscriber=lambda cb: commands.add_change_callback(cb),
            parent=parent,
        )
        self.enable_undo_redo(commands)
        self.populate()
        self._connect_paths_signal()

        # G.6.6 cross-tab linking: при активации рецепта подсветить его сервисы.
        # Подписка хранится в self (EventBus держит сильную ссылку на handler).
        self._highlighted_service_keys: list[str] = []
        self._recipe_activated_sub = services.events.subscribe(RecipeActivated, self._on_recipe_activated)

    @classmethod
    def create(
        cls,
        services: AppServices,
        runtime: RuntimeDeps = RuntimeDeps(),
    ) -> "ServicesTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        ServicesTab не использует runtime-зависимостей.
        """
        return cls(services)

    def _tree_object_name(self) -> str:
        return "ServicesTreeNav"

    def _connect_paths_signal(self) -> None:
        """Подключить сигнал catalog_updated от PathsSection к refresh_catalog()."""
        # Ищем секцию __service_paths__ среди уже построенных spec
        for spec in self._sections_specs:
            if spec.key == "__service_paths__":
                # Секция lazy — экземпляр создаётся при первом обращении.
                # Подключим сигнал если виджет уже построен, иначе это сделает
                # _build_section при первом открытии секции.
                # Используем safe-getter через spec._instance если доступен.
                instance = getattr(spec, "_instance", None)
                if instance is not None:
                    widget = getattr(instance, "_widget", None)
                    if widget is not None and hasattr(widget, "catalog_updated"):
                        widget.catalog_updated.connect(self.refresh_catalog)
                break

    def refresh_catalog(self) -> None:
        """Перестроить секции после изменения директорий сервисов.

        Вызывается по сигналу catalog_updated из ServicePathsSubtabWidget.
        Пересобирает _sections_specs и перезаполняет дерево навигации.
        """
        new_sections = build_services_sections(self._services)
        self._sections_specs = new_sections
        self.populate()

    # ------------------------------------------------------------------ #
    #  G.6.6 cross-tab linking                                            #
    # ------------------------------------------------------------------ #

    def _on_recipe_activated(self, event: RecipeActivated) -> None:
        """Подсветить сервисы активированного рецепта (active_services).

        Читает active_services из рецепта (оба формата: верхний уровень / data).
        Пустой список или нечитаемый рецепт → снимает прежнюю подсветку.
        """
        active_services: list[str] = []
        recipes = self._services.recipes
        raw = recipes.read_raw(event.slug) if recipes is not None else None
        if isinstance(raw, dict):
            svc = raw.get("active_services")
            if svc is None:
                svc = raw.get("data", {}).get("active_services") if isinstance(raw.get("data"), dict) else None
            if isinstance(svc, list):
                active_services = [str(s) for s in svc]
        self.highlight_active_services(active_services)

    def highlight_active_services(self, service_ids: list[str]) -> None:
        """Жирным выделить tree-nav узлы указанных сервисов; снять прежнюю подсветку."""
        for key in self._highlighted_service_keys:
            self._set_item_bold(key, False)
        self._highlighted_service_keys = [sid for sid in service_ids if self._set_item_bold(sid, True)]

    def _set_item_bold(self, key: str, bold: bool) -> bool:
        """Установить/снять bold для tree-nav узла по ключу. True если узел найден."""
        item = find_tree_item(self._tree_nav.invisibleRootItem(), key)
        if item is None:
            return False
        font = item.font(0)
        font.setBold(bold)
        item.setFont(0, font)
        return True
