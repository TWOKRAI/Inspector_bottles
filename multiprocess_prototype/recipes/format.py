# -*- coding: utf-8 -*-
"""format.py — единая нормализация raw-рецепта v3 на запись (one source of truth).

Презентеры (Recipes/Pipeline) сохраняют живую топологию в рецепт. Раньше каждый делал
это inline и по-разному (legacy ``data:``-вложение, разные места для displays), что и
породило баг #4. Здесь — ОДНА точка сборки v3-raw для записи:
  - top-level ``blueprint`` (displays ВНУТРИ ``blueprint.displays``);
  - прочие top-level ключи (name/version/description/active_services) не тронуты;
  - остаточный legacy-мусор ``data:``/``meta:`` (от старой порчи движком) убирается.

Результат пишется через ``RecipeStore.save_raw`` (ruamel round-trip — комментарии целы).
"""

from __future__ import annotations

from typing import Any

__all__ = ["normalize_recipe_v3_raw"]


def normalize_recipe_v3_raw(
    raw: dict[str, Any],
    blueprint: dict[str, Any],
    gui_positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собрать v3-raw рецепта для записи из существующего raw + новой топологии.

    Args:
        raw: текущий raw-dict рецепта (из ``RecipeStore.read_raw``).
        blueprint: новый blueprint (``{name?, description?, processes, wires, displays}``);
            displays ДОЛЖНЫ лежать внутри blueprint (single source — ``blueprint.displays``).
        gui_positions: позиции узлов GUI (top-level). Пустые — не пишутся.

    Returns:
        Новый dict (копия raw) с обновлёнными top-level секциями, без ``data``/``meta``.
    """
    result = dict(raw)
    result.pop("data", None)  # legacy-envelope от старой порчи — выкидываем
    result.pop("meta", None)
    result["blueprint"] = blueprint
    if gui_positions:
        result["gui_positions"] = gui_positions
    return result
