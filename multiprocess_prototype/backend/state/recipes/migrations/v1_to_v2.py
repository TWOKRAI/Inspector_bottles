"""Миграция рецепта v1 → v2: processing_blocks → nodes (Phase 9.12).

Чистый модуль без I/O — только словарные трансформации над plain dict.
Используется RecipeEngine при обнаружении legacy-формата (processing_blocks в region).

Legacy-формат (Phase 0-4):
    region = {"processing_blocks": {block_id: {"enabled": bool, "params": {"type": str, ...}}}}

Новый формат (Phase 5a+):
    region = {"nodes": {node_id: {"node_id": str, "operation_ref": str, "enabled": bool,
                                   "params": {...}, "inputs": [...], ...}}}

Семантика linear chain:
    Блоки выполнялись последовательно (dict-iteration order).
    Первая нода читает из "frame", остальные — из предыдущей ноды.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from multiprocess_framework.modules.recipe.migrations import migration

logger = logging.getLogger(__name__)

RECIPE_VERSION_V1 = 1  # legacy: regions содержат processing_blocks
RECIPE_VERSION_V2 = 2  # current: regions содержат nodes

# doc_type реестра миграций (C2, ADR-RCP-003) — различает эту миграцию (regions
# внутри data.cameras: processing_blocks → nodes) от одноимённой
# recipes/migrations/format_v1_to_v2.py::migrate_v1_to_v2 (topology-файл целиком:
# slot-based → blueprint) — разные doc_type, НЕ конфликтуют в общем реестре.
DOC_TYPE = "recipe.config_snapshot"


def needs_migration(recipe_data: dict) -> bool:
    """True если в data найдена хотя бы одна region с непустыми processing_blocks.

    Проходит по всем cameras.*.regions.* для поиска legacy-полей.
    """
    cameras = recipe_data.get("cameras", {})
    if not isinstance(cameras, dict):
        return False

    for cam_data in cameras.values():
        if not isinstance(cam_data, dict):
            continue
        regions = cam_data.get("regions", {})
        if not isinstance(regions, dict):
            continue
        for region_data in regions.values():
            if not isinstance(region_data, dict):
                continue
            processing_blocks = region_data.get("processing_blocks", {})
            if processing_blocks:
                return True

    return False


def _convert_block_to_node(block_id: str, block: Any, prev_node_id: str | None) -> dict:
    """Конвертирует один processing_block в dict ProcessingNode.

    Args:
        block_id: ключ блока (становится node_id).
        block: dict с полями enabled, params.
        prev_node_id: node_id предыдущего узла (None — первый, читает "frame").

    Returns:
        dict в формате ProcessingNode (сериализованный как plain dict).
    """
    if not isinstance(block, dict):
        logger.warning("processing_block '%s' не является dict, пропускаем конвертацию", block_id)
        return {
            "node_id": block_id,
            "operation_ref": "unknown",
            "enabled": True,
            "params": {},
            "inputs": _make_inputs(prev_node_id),
        }

    enabled = block.get("enabled", True)

    # Проверяем наличие поля params (None и отсутствующее — одинаково)
    params_raw = block.get("params")

    # Извлекаем operation_ref из params["type"]
    if params_raw is None or not isinstance(params_raw, dict):
        # params отсутствует или не является dict
        logger.warning(
            "processing_block '%s': params отсутствует или не является dict, operation_ref='unknown'",
            block_id,
        )
        operation_ref = "unknown"
        params = {}
    elif "type" in params_raw:
        operation_ref = params_raw["type"]
        # params без ключа "type"
        params = {k: v for k, v in params_raw.items() if k != "type"}
    else:
        # params есть, но нет поля "type" — fallback
        logger.warning(
            "processing_block '%s': params не содержит поле 'type', "
            "используем fallback operation_ref='color_detection'",
            block_id,
        )
        operation_ref = "color_detection"
        params = dict(params_raw)

    return {
        "node_id": block_id,
        "operation_ref": operation_ref,
        "enabled": enabled,
        "params": params,
        "inputs": _make_inputs(prev_node_id),
        "outputs": [],
        "display_targets": [],
        "process_id": "processor",
        "worker_id": None,
        "position": None,
        "channel_prefix": None,
    }


def _make_inputs(prev_node_id: str | None) -> list[dict]:
    """Формирует список inputs для ноды.

    Первая нода (prev_node_id=None) читает из "frame".
    Остальные ссылаются на предыдущую ноду.
    """
    source = prev_node_id if prev_node_id is not None else "frame"
    return [
        {
            "source": source,
            "output_port": "out",
            "input_port": "in",
        }
    ]


def _convert_region(region_data: dict) -> dict:
    """Конвертирует один region dict из legacy в новый формат.

    Правила:
    1. Если processing_blocks непустой И nodes пустой/отсутствует → конвертируем.
    2. Если оба непусты → оставляем как есть (warning), processing_blocks НЕ удаляем.
    3. Если processing_blocks пуст или отсутствует → ничего не делаем.

    Returns:
        Новый dict региона (глубокая копия с изменениями).
    """
    result = copy.deepcopy(region_data)

    processing_blocks = result.get("processing_blocks", {})
    nodes = result.get("nodes", {})

    # Случай 3: нечего конвертировать
    if not processing_blocks:
        return result

    # Случай 2: обе ветки непусты → предупреждение, оставляем как есть
    if nodes:
        logger.warning(
            "Region содержит непустые processing_blocks И nodes одновременно — "
            "конверсия пропущена, ручная проверка обязательна"
        )
        return result

    # Случай 1: конвертируем processing_blocks → nodes
    new_nodes: dict[str, dict] = {}
    prev_node_id: str | None = None

    for block_id, block in processing_blocks.items():
        node_dict = _convert_block_to_node(block_id, block, prev_node_id)
        new_nodes[block_id] = node_dict
        prev_node_id = block_id

    result["nodes"] = new_nodes
    # Удаляем legacy-поле — backup уже создан на уровне RecipeEngine
    del result["processing_blocks"]

    return result


@migration(DOC_TYPE, from_=RECIPE_VERSION_V1, to=RECIPE_VERSION_V2)
def migrate_recipe_data(recipe_data: dict) -> dict:
    """Принимает recipe['data'] (cameras-ветку и др.), возвращает новый dict.

    Исходный dict не мутируется — возвращается глубокая копия с изменениями.

    Edge cases:
    - data без cameras → возвращаем deepcopy без изменений.
    - Camera без regions → пропускаем.
    - Region без processing_blocks → оставляем как есть.
    """
    result = copy.deepcopy(recipe_data)

    cameras = result.get("cameras", {})
    if not isinstance(cameras, dict):
        return result

    for cam_id, cam_data in cameras.items():
        if not isinstance(cam_data, dict):
            continue
        regions = cam_data.get("regions", {})
        if not isinstance(regions, dict):
            continue

        new_regions: dict[str, dict] = {}
        for region_id, region_data in regions.items():
            if not isinstance(region_data, dict):
                new_regions[region_id] = region_data
                continue
            new_regions[region_id] = _convert_region(region_data)

        cameras[cam_id]["regions"] = new_regions

    return result


__all__ = [
    "RECIPE_VERSION_V1",
    "RECIPE_VERSION_V2",
    "needs_migration",
    "migrate_recipe_data",
]
