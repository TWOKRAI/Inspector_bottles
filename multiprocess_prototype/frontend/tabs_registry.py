"""TABS — декларативный реестр вкладок приложения (единый источник, NEW-D1).

Единственное место, где перечислены вкладки прототипа: их состав, порядок,
право на просмотр и фабрика содержимого. Из этого списка деривятся:

- набор вкладок и их порядок в UI (через ``TabRegistry`` из frontend_module);
- каталог permissions приложения (``register_all_permissions``, D-4);
- паритет с predefined-ролями auth-слоя (характеризационный тест, D-5).

Механизм (построение/ленивость/permission-фильтр) живёт во frontend_module
(``TabRegistry``); здесь — только прикладная декларация ``TABS: list[TabSpec]``.

Фабрики — deferred-import замыкания: конкретный виджет импортируется в момент
создания вкладки, а не при загрузке модуля (иначе circular imports — вкладки
тянут services/widgets). Сигнатура фабрики: ``(AppServices, RuntimeDeps) -> QWidget``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.tabs import TabSpec

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


# ---------------------------------------------------------------------------
# Deferred-import фабрики вкладок
# ---------------------------------------------------------------------------
#
# Каждая функция импортирует свою вкладку лениво (внутри тела), чтобы избежать
# циклических импортов при загрузке этого модуля.


def _settings_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.settings import SettingsTab

    return SettingsTab.create(services, runtime)


def _recipes_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.recipes import RecipesTab

    return RecipesTab.create(services, runtime)


def _processes_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.processes import ProcessesTab

    return ProcessesTab.create(services, runtime)


def _services_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.services import ServicesTab

    return ServicesTab.create(services, runtime)


def _plugins_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.plugins import PluginsTab

    return PluginsTab.create(services, runtime)


def _pipeline_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.pipeline import PipelineTab

    return PipelineTab.create(services, runtime)


def _displays_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.displays import DisplaysTab

    return DisplaysTab.create(services, runtime)


def _observability_factory(services: "AppServices", runtime: "RuntimeDeps") -> "QWidget":
    from .widgets.tabs.observability import ObservabilityTabs

    return ObservabilityTabs.create(services, runtime)


# ---------------------------------------------------------------------------
# TABS — единый источник (порядок = порядок вкладок в UI)
# ---------------------------------------------------------------------------

TABS: list[TabSpec] = [
    TabSpec(
        id="settings",
        title="Settings",
        view_permission="tabs.settings.view",
        factory=_settings_factory,
        description="Администрирование, конфиг системы",
    ),
    TabSpec(
        id="recipes",
        title="Recipes",
        view_permission="tabs.recipes.view",
        factory=_recipes_factory,
        description="Пресеты/рецепты обработки",
    ),
    TabSpec(
        id="processes",
        title="Processes",
        view_permission="tabs.processes.view",
        factory=_processes_factory,
        description="Управление процессами",
    ),
    TabSpec(
        id="services",
        title="Services",
        view_permission="tabs.services.view",
        factory=_services_factory,
        description="Камеры SDK, БД, робот, нейронки",
    ),
    TabSpec(
        id="plugins",
        title="Plugins",
        view_permission="tabs.plugins.view",
        factory=_plugins_factory,
        description="Обработка изображений, мосты",
    ),
    TabSpec(
        id="pipeline",
        title="Pipeline",
        view_permission="tabs.pipeline.view",
        factory=_pipeline_factory,
        description="Визуальный конструктор цепочек",
    ),
    TabSpec(
        id="displays",
        title="Displays",
        view_permission="tabs.displays.view",
        factory=_displays_factory,
        description="Управление экранами вывода",
    ),
    TabSpec(
        id="observability",
        title="Наблюдаемость",
        view_permission="tabs.observability.view",
        factory=_observability_factory,
        description="Логи / Ошибки / Статистика — история и живой хвост (Ф5.19)",
    ),
]


def tab_ids() -> list[str]:
    """Список id вкладок в порядке отображения (единый источник для деривации)."""
    return [spec.id for spec in TABS]
