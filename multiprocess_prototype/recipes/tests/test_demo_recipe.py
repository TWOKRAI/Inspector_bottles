"""test_demo_recipe.py — Integration-тесты demo_webcam_split_merge.yaml.

Проверяют:
1. Файл рецепта присутствует на диске.
2. RecipeManager.list() видит рецепт, read_recipe возвращает корректный dict.
3. Все плагины из blueprint зарегистрированы в PluginRegistry.
4. Wire-источники/приёмники ссылаются на существующие процессы.
5. Секции active_services и display_bindings присутствуют.

Запуск: python -m pytest multiprocess_prototype/recipes/tests/test_demo_recipe.py -v
(из корня проекта)

Refs: plans/prototype-skeleton-2026-05/phase-7b-telemetry-and-demo.md
"""

from __future__ import annotations

from pathlib import Path

import yaml

# ------------------------------------------------------------------ #
# Пути
# ------------------------------------------------------------------ #

# Корень репозитория — parent^3 от этого файла
# tests/ <- recipes/ <- multiprocess_prototype/ <- PROJECT_ROOT
_HERE = Path(__file__).resolve().parent
_RECIPES_DIR = _HERE.parent
_RECIPE_SLUG = "demo_webcam_split_merge"
_RECIPE_FILE = _RECIPES_DIR / f"{_RECIPE_SLUG}.yaml"

# Директории плагинов для discover()
_PROJECT_ROOT = _RECIPES_DIR.parent.parent
_PLUGINS_PROCESSING = str(_PROJECT_ROOT / "Plugins" / "processing")
_PLUGINS_SOURCES = str(_PROJECT_ROOT / "Plugins" / "sources")
_PLUGINS_RENDER = str(_PROJECT_ROOT / "Plugins" / "render")


# ------------------------------------------------------------------ #
# Вспомогательные функции
# ------------------------------------------------------------------ #


def _load_recipe_raw() -> dict:
    """Прочитать YAML рецепта напрямую (без RecipeManager)."""
    with open(_RECIPE_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def _make_manager():
    """Создать RecipeManager, указывающий на реальную директорию рецептов."""
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import (
        RecipeEngine,
    )
    from multiprocess_prototype.recipes.manager import RecipeManager

    store = TreeStore()
    engine = RecipeEngine(store=store, recipes_dir=_RECIPES_DIR)
    return RecipeManager(engine=engine, state_proxy=None, logger=None)


def _collect_plugin_names(blueprint: dict) -> list[str]:
    """Собрать все plugin_name из blueprint.processes."""
    names: list[str] = []
    for process in blueprint.get("processes", []):
        for plugin in process.get("plugins", []):
            name = plugin.get("plugin_name", "")
            if name:
                names.append(name)
    return names


def _collect_process_names(blueprint: dict) -> set[str]:
    """Собрать все process_name из blueprint.processes."""
    return {p["process_name"] for p in blueprint.get("processes", []) if "process_name" in p}


# ------------------------------------------------------------------ #
# Тест 1 — файл рецепта присутствует
# ------------------------------------------------------------------ #


def test_demo_recipe_file_exists() -> None:
    """Файл demo_webcam_split_merge.yaml должен присутствовать в директории рецептов."""
    assert _RECIPE_FILE.exists(), (
        f"Файл рецепта не найден: {_RECIPE_FILE}\n"
        "Создай файл multiprocess_prototype/recipes/demo_webcam_split_merge.yaml"
    )


# ------------------------------------------------------------------ #
# Тест 2 — RecipeManager.list() и read_recipe()
# ------------------------------------------------------------------ #


def test_demo_recipe_loads_via_manager() -> None:
    """RecipeManager.list() содержит slug рецепта.

    read_recipe(slug) возвращает dict с ключом 'blueprint'.
    """
    manager = _make_manager()

    # Проверяем что slug есть в списке
    available = manager.list()
    assert _RECIPE_SLUG in available, f"Рецепт '{_RECIPE_SLUG}' не найден в списке: {available}"

    # Читаем рецепт через manager
    recipe_dict = manager.read_recipe(_RECIPE_SLUG)
    assert recipe_dict is not None, f"RecipeManager.read_recipe('{_RECIPE_SLUG}') вернул None"
    assert isinstance(recipe_dict, dict), f"read_recipe должен возвращать dict, получено: {type(recipe_dict)}"

    # Верхнеуровневые обязательные поля
    assert "blueprint" in recipe_dict, f"Рецепт должен содержать ключ 'blueprint'. Ключи: {list(recipe_dict.keys())}"
    assert "version" in recipe_dict, f"Рецепт должен содержать ключ 'version'. Ключи: {list(recipe_dict.keys())}"
    assert recipe_dict["version"] == 3, f"Ожидается version=3, получено: {recipe_dict['version']}"

    # Blueprint содержит processes и wires
    blueprint = recipe_dict["blueprint"]
    assert isinstance(blueprint, dict), f"blueprint должен быть dict, получено: {type(blueprint)}"
    assert "processes" in blueprint, "blueprint должен содержать 'processes'"
    assert "wires" in blueprint, "blueprint должен содержать 'wires'"
    assert len(blueprint["processes"]) == 4, f"Ожидается 4 процесса, получено: {len(blueprint['processes'])}"


# ------------------------------------------------------------------ #
# Тест 3 — все плагины зарегистрированы в PluginRegistry
# ------------------------------------------------------------------ #


def test_demo_recipe_blueprint_references_existing_plugins() -> None:
    """Все plugin_name из blueprint.processes зарегистрированы в PluginRegistry.

    Выполняет PluginRegistry.discover по директориям Plugins/,
    затем проверяет каждый plugin_name из рецепта.
    """
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    # Запускаем discover — @register_plugin срабатывает при импорте
    PluginRegistry.discover(
        _PLUGINS_PROCESSING,
        _PLUGINS_SOURCES,
        _PLUGINS_RENDER,
    )

    recipe_dict = _load_recipe_raw()
    blueprint = recipe_dict["blueprint"]
    plugin_names = _collect_plugin_names(blueprint)

    assert len(plugin_names) > 0, "blueprint должен содержать хотя бы один плагин"

    # Ожидаемые плагины из demo-рецепта
    expected_plugins = {
        "capture",
        "resize",
        "region_split",
        "grayscale",
        "color_mask",
        "negative",
        "blur",
        "stitcher",
        "render_overlay",
    }

    missing: list[str] = []
    for name in plugin_names:
        entry = PluginRegistry.get(name)
        if entry is None:
            missing.append(name)

    assert not missing, (
        f"Следующие плагины из рецепта не найдены в PluginRegistry: {missing}\n"
        f"Зарегистрированные плагины: {PluginRegistry.names()}"
    )

    # Дополнительно — все ожидаемые плагины покрыты
    for name in expected_plugins:
        assert PluginRegistry.get(name) is not None, f"Ожидаемый плагин '{name}' не зарегистрирован в PluginRegistry"


# ------------------------------------------------------------------ #
# Тест 4 — wire source/target ссылаются на существующие процессы
# ------------------------------------------------------------------ #


def test_demo_recipe_wires_reference_existing_processes() -> None:
    """Все process_name в wires (первый сегмент адреса) должны существовать в processes."""
    recipe_dict = _load_recipe_raw()
    blueprint = recipe_dict["blueprint"]

    process_names = _collect_process_names(blueprint)
    wires = blueprint.get("wires", [])

    assert len(wires) > 0, "blueprint должен содержать хотя бы один wire"

    invalid_refs: list[str] = []
    for wire in wires:
        for key in ("source", "target"):
            addr = wire.get(key, "")
            if not addr:
                invalid_refs.append(f"wire без ключа '{key}': {wire}")
                continue
            parts = addr.split(".")
            if len(parts) < 3:
                invalid_refs.append(f"wire '{key}' имеет неверный формат: '{addr}'")
                continue
            proc_name = parts[0]
            if proc_name not in process_names:
                invalid_refs.append(f"wire '{key}' ссылается на несуществующий процесс '{proc_name}' (адрес: '{addr}')")

    assert not invalid_refs, "Ошибки в wire-адресах:\n" + "\n".join(f"  - {e}" for e in invalid_refs)


# ------------------------------------------------------------------ #
# Тест 5 — display_bindings и active_services присутствуют
# ------------------------------------------------------------------ #


def test_demo_recipe_has_display_bindings() -> None:
    """Рецепт содержит секции display_bindings и active_services."""
    recipe_dict = _load_recipe_raw()

    # active_services
    assert "active_services" in recipe_dict, "Рецепт должен содержать секцию 'active_services'"
    active_services = recipe_dict["active_services"]
    assert isinstance(active_services, list), "active_services должен быть списком"
    assert len(active_services) >= 1, "active_services должен содержать хотя бы один сервис"

    # display_bindings
    assert "display_bindings" in recipe_dict, "Рецепт должен содержать секцию 'display_bindings'"
    bindings = recipe_dict["display_bindings"]
    assert isinstance(bindings, list), "display_bindings должен быть списком"
    assert len(bindings) == 2, f"Ожидается 2 display_binding, получено: {len(bindings)}"

    # Проверяем структуру каждого binding (формат v3: node_id/display_id)
    for binding in bindings:
        assert "node_id" in binding, f"display_binding без 'node_id': {binding}"
        assert "display_id" in binding, f"display_binding без 'display_id': {binding}"
