"""detect.py — распознавание формата рецепта (v3-blueprint vs config-snapshot).

Purpose:
    Рецепты бывают двух родов: config-snapshot (envelope ``{meta, data}`` — v1/v2,
    реплеится в TreeStore) и v3-blueprint (плоский top-level ``{name, version,
    blueprint, ...}`` — топология, которую запускает recipe-driven backend, а НЕ
    TreeStore). Смешение форматов на load() затирало blueprint миграцией пустого
    ``data`` (баг fix recipe-v3-engine-decouple). Здесь — единственная точка,
    отвечающая на вопрос «это v3-blueprint?».

Public API:
    - is_v3_recipe — True если dict рецепта в формате v3.

Stability: lite
"""

from __future__ import annotations

from typing import Any

__all__ = ["is_v3_recipe"]


def is_v3_recipe(recipe: Any) -> bool:
    """True если файл — рецепт формата v3 (top-level blueprint / version >= 3).

    Маркер v3 — наличие ключа ``blueprint`` на верхнем уровне (плоский формат без
    envelope ``data``). Дополнительно ``version >= 3`` как явная отметка. Битый файл
    (blueprint + остаточные data/meta от прошлой порчи) тоже распознаётся как v3 по
    наличию ``blueprint`` — повторной порчи не будет.

    Pre:
      - recipe — произвольный объект (обычно dict из yaml.safe_load).
    Post:
      - dict с ключом ``blueprint`` → True.
      - dict с ``version`` (int) >= 3 → True.
      - иначе (config-snapshot, None, не-dict) → False.
    """
    if not isinstance(recipe, dict):
        return False
    if "blueprint" in recipe:
        return True
    version = recipe.get("version")
    return isinstance(version, int) and version >= 3
