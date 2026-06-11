"""devices_sync — извлечение и инжект устройств рецепта в процесс devices.

Р11 плана device-hub: секция ``devices:`` в рецепте — top-level (sibling ``blueprint:``).
``unwrap_recipe`` выбрасывает её, поэтому извлечение обязано идти от raw-yaml ДО unwrap.

Два пути доставки:
  (a) Boot: ``extract_recipe_devices(raw)`` -> inject в конфиг плагина device_hub
      merged-топологии (``inject_recipe_devices``).
  (b) Hot-активация GUI: ``device_upsert_many`` + connect ДО replace_blueprint
      (в презентере рецептов).

Refs: plans/device-hub.md Фаза 3, Р11
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_recipe_devices(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Извлечь top-level ``devices:`` из raw-yaml рецепта ДО unwrap.

    Валидация: элемент — dict с обязательными полями ``id`` и ``kind``.
    Битые записи — пропуск с warning.

    Args:
        raw: raw-dict рецепта (из yaml.safe_load, до unwrap_recipe).

    Returns:
        Список валидных device-dict'ов (может быть пуст).
    """
    devices_raw = raw.get("devices")
    if not isinstance(devices_raw, list):
        return []

    result: list[dict[str, Any]] = []
    for i, entry in enumerate(devices_raw):
        if not isinstance(entry, dict):
            logger.warning("devices_sync: devices[%d] не является dict — пропущен", i)
            continue
        if "id" not in entry or "kind" not in entry:
            logger.warning("devices_sync: devices[%d] без id/kind — пропущен: %s", i, entry)
            continue
        result.append(entry)

    return result


def inject_recipe_devices(
    merged_topology: dict[str, Any],
    recipe_devices: list[dict[str, Any]],
    recipe_name: str = "",
) -> dict[str, Any]:
    """Инжектировать recipe_devices в конфиг плагина device_hub merged-топологии.

    Ищет процесс ``devices`` -> плагин ``device_hub`` -> добавляет в его конфиг
    ``recipe_devices: [...]`` и ``recipe_origin: "recipe:<name>"``.

    Мутирует копию merged_topology (НЕ оригинал).

    Args:
        merged_topology: merged-топология (после merge_topologies).
        recipe_devices:  список device-dict'ов из extract_recipe_devices.
        recipe_name:     имя рецепта (для origin).

    Returns:
        Обновлённая merged-топология с recipe_devices в конфиге device_hub.
    """
    if not recipe_devices:
        return merged_topology

    result = copy.deepcopy(merged_topology)
    processes = result.get("processes", [])

    for proc in processes:
        if proc.get("process_name") != "devices":
            continue
        for plugin_cfg in proc.get("plugins", []):
            pname = plugin_cfg.get("plugin_name", "")
            if pname == "device_hub":
                plugin_cfg["recipe_devices"] = recipe_devices
                if recipe_name:
                    plugin_cfg["recipe_origin"] = f"recipe:{recipe_name}"
                logger.info(
                    "devices_sync: injected %d recipe_devices в device_hub (recipe=%s)",
                    len(recipe_devices),
                    recipe_name,
                )
                return result

    logger.warning("devices_sync: процесс devices / плагин device_hub не найден в merged-топологии")
    return result
