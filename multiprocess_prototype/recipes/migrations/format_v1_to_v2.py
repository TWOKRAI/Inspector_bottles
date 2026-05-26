"""Миграция рецепта v1 → v2: slot-based topology → blueprint.

Формат v1 (slot-based, до Phase 5):
    {
        "name": "cup_inspection",
        "description": "...",
        "topology": {
            "processes": [...],
            "wires": [...]
        }
    }

Формат v2 (blueprint-based, Phase 5+):
    {
        "version": 2,
        "name": "cup_inspection",
        "description": "...",
        "blueprint": {
            "processes": [...],
            "wires": [...]
        },
        "active_services": [...],
        "display_bindings": [{"source": "...", "display": "..."}]
    }

Внимание: эта миграция — другая, чем backend/state/recipes/migrations/v1_to_v2.py
(та мигрирует внутреннюю структуру processing_blocks → nodes внутри camera/region).

Данная миграция конвертирует внешний формат файла рецепта:
topology dict → blueprint + active_services + display_bindings.

Чистый модуль без I/O — только dict-трансформации.
"""

from __future__ import annotations

import copy
from typing import Any


def is_v1_recipe(data: Any) -> bool:
    """True если данные — это рецепт v1 (без поля version или version < 2).

    Graceful: None или не-dict → False (без исключений).

    Args:
        data: произвольный объект для проверки.

    Returns:
        True если это v1-рецепт, требующий миграции.
    """
    if not isinstance(data, dict):
        return False

    # Если нет ключа version — считаем legacy (v1)
    if "version" not in data:
        return True

    # Явно проверяем версию
    version = data.get("version")
    if not isinstance(version, int):
        return True

    return version < 2


def _extract_display_bindings(wires: list[Any]) -> list[dict[str, str]]:
    """Извлекает display_bindings из списка wires.

    Ищет wire-записи с target вида *.display.* или display_* и
    формирует список {source, display}.

    Args:
        wires: список wire-записей из topology.

    Returns:
        Список dict {source, display}.
    """
    bindings: list[dict[str, str]] = []

    if not isinstance(wires, list):
        return bindings

    for wire in wires:
        if not isinstance(wire, dict):
            continue

        target = wire.get("target", "")
        source = wire.get("source", "")

        if not isinstance(target, str) or not isinstance(source, str):
            continue

        # Проверяем что target указывает на display-компонент
        is_display_target = ".display." in target or target.startswith("display_") or target.startswith("display.")

        if is_display_target:
            # Определяем имя дисплея: берём последний сегмент или весь target
            parts = target.split(".")
            display_name = parts[-1] if len(parts) > 1 else target

            bindings.append({"source": source, "display": display_name})

    return bindings


def _extract_active_services(processes: list[Any]) -> list[str]:
    """Извлекает active_services из списка процессов.

    Ищет плагины с category == "service" в каждом процессе.
    Если plugin_registry не доступен — возвращает пустой список.

    TODO: при наличии plugin_registry подтягивать metadata о категориях плагинов.
          Сейчас используется поле "category" непосредственно из конфига плагина.

    Args:
        processes: список процессов из topology.

    Returns:
        Список имён сервис-плагинов.
    """
    services: list[str] = []

    if not isinstance(processes, list):
        return services

    for process in processes:
        if not isinstance(process, dict):
            continue

        plugins = process.get("plugins", [])
        if not isinstance(plugins, list):
            continue

        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue

            # Проверяем категорию плагина
            category = plugin.get("category", "")
            if category == "service":
                plugin_name = plugin.get("name") or plugin.get("plugin_id", "")
                if plugin_name:
                    services.append(str(plugin_name))

    return services


def migrate_v1_to_v2(data: dict) -> dict:
    """Мигрирует рецепт v1 (topology-based) в формат v2 (blueprint-based).

    Принимает данные dict (секция recipe.data или весь файл v1) и
    возвращает новый dict в формате v2.

    Исходный dict не мутируется — возвращается новый dict.

    Конвертация:
    - topology → blueprint (topology["processes"] → blueprint["processes"],
                             topology["wires"] → blueprint["wires"])
    - display wires → display_bindings
    - service plugins → active_services
    - version устанавливается в 2

    Graceful: отсутствующие поля заменяются пустыми значениями.

    Args:
        data: dict рецепта v1 с ключами name, description, topology.

    Returns:
        dict рецепта v2 с ключами version, name, description, blueprint,
        active_services, display_bindings.
    """
    if not isinstance(data, dict):
        # Graceful fallback для не-dict данных
        return {
            "version": 2,
            "name": "",
            "description": "",
            "blueprint": {"processes": [], "wires": []},
            "active_services": [],
            "display_bindings": [],
        }

    # Берём topology — основной источник blueprint
    topology = data.get("topology", {}) or {}
    if not isinstance(topology, dict):
        topology = {}

    processes = topology.get("processes", []) or []
    if not isinstance(processes, list):
        processes = []

    wires = topology.get("wires", []) or []
    if not isinstance(wires, list):
        wires = []

    # Формируем blueprint (глубокая копия для изоляции)
    blueprint = {
        "processes": copy.deepcopy(processes),
        "wires": copy.deepcopy(wires),
    }

    # Извлекаем display_bindings из wires
    display_bindings = _extract_display_bindings(wires)

    # Извлекаем active_services из процессов
    active_services = _extract_active_services(processes)

    return {
        "version": 2,
        "name": data.get("name", "") or "",
        "description": data.get("description", "") or "",
        "blueprint": blueprint,
        "active_services": active_services,
        "display_bindings": display_bindings,
    }


__all__ = ["migrate_v1_to_v2", "is_v1_recipe"]
