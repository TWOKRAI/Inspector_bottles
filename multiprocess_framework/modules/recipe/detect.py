"""detect.py — распознавание формата рецепта (v3-blueprint vs config-snapshot).

Purpose:
    Рецепты бывают двух родов: config-snapshot (envelope ``{meta, data}`` — v1/v2,
    реплеится в TreeStore) и v3-blueprint (плоский top-level ``{name, version,
    blueprint, ...}`` — топология, которую запускает recipe-driven backend, а НЕ
    TreeStore). Смешение форматов на load() затирало blueprint миграцией пустого
    ``data`` (баг fix recipe-v3-engine-decouple). Здесь — единственная точка,
    отвечающая на вопрос «это v3-blueprint?».

    До C2 (ADR-RCP-003) проверка ``"blueprint" in raw`` была разъехавшейся по
    прототипу (unwrap_recipe, recipe_io.py, RecipesPresenter, RecipeStore —
    дубль D6): каждый call-site независимо проверял наличие ключа. Здесь —
    единая точка «формы» (has_top_level_blueprint / nested_blueprint_data),
    от которой зависят и is_v3_recipe, и прикладные call-sites.

Public API:
    - is_v3_recipe — True если dict рецепта в формате v3.
    - has_top_level_blueprint — True если dict содержит ``blueprint`` на верхнем уровне.
    - nested_blueprint_data — вложенный ``data`` с ``blueprint`` (legacy v2) или None.

Stability: lite
"""

from __future__ import annotations

from typing import Any

__all__ = ["is_v3_recipe", "has_top_level_blueprint", "nested_blueprint_data"]


def has_top_level_blueprint(raw: Any) -> bool:
    """True если raw — dict с ключом ``blueprint`` на верхнем уровне.

    Единая «форма» v3-blueprint, используемая как is_v3_recipe (RecipeEngine),
    так и прикладными call-sites (unwrap_recipe, recipe_io.py, RecipesPresenter,
    RecipeStore) — вместо разъехавшихся ad-hoc проверок ``"blueprint" in raw``
    (C2, ADR-RCP-003, дубль D6).

    Pre:
      - raw — произвольный объект.
    Post:
      - dict с ключом ``blueprint`` → True, иначе (не-dict или ключа нет) → False.
    """
    return isinstance(raw, dict) and "blueprint" in raw


def nested_blueprint_data(raw: Any) -> dict[str, Any] | None:
    """Вернуть raw["data"], если это dict со вложенным ``blueprint`` (legacy v2).

    Форма ``{"data": {"blueprint": {...}}}`` — рецепт-топология, у которой
    blueprint лежит не на верхнем уровне, а внутри envelope ``data``.

    Pre:
      - raw — произвольный объект.
    Post:
      - raw — dict, raw["data"] — dict с ключом "blueprint" → возвращает raw["data"].
      - иначе → None.
    """
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    if isinstance(data, dict) and "blueprint" in data:
        return data
    return None


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
    if has_top_level_blueprint(recipe):
        return True
    if not isinstance(recipe, dict):
        return False
    version = recipe.get("version")
    return isinstance(version, int) and version >= 3
