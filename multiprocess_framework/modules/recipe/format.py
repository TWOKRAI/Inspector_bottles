# -*- coding: utf-8 -*-
"""format.py — единая нормализация raw-рецепта v3 на запись (one source of truth).

Purpose:
    Презентеры (Recipes/Pipeline) сохраняют живую топологию в рецепт. Раньше каждый
    делал это inline и по-разному (legacy ``data:``-вложение, разные места для
    displays), что породило баг #4. Здесь — ОДНА точка сборки v3-raw для записи:
      - top-level ``blueprint`` (displays ВНУТРИ ``blueprint.displays``);
      - прочие top-level ключи (name/version/description/…) не тронуты;
      - остаточный legacy-мусор ``data:``/``meta:`` (от старой порчи движком) убирается;
      - legacy top-level ``gui_positions`` вычищается: канонические позиции живут в
        ``blueprint.metadata.gui_positions`` (их кладёт вызывающий), а top-level-дубль
        не читает ни один live-путь (аудит Ф4.8, AU-1). Так GUI-save становится
        канонизатором — старый дубль не переживает перезапись.

    Результат пишется через comment-preserving writer (ruamel round-trip) — комментарии
    целы.

Public API:
    - normalize_recipe_v3_raw — собрать v3-raw рецепта для записи.

Stability: lite
"""

from __future__ import annotations

from typing import Any

__all__ = ["normalize_recipe_v3_raw"]


def normalize_recipe_v3_raw(
    raw: dict[str, Any],
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    """Собрать v3-raw рецепта для записи из существующего raw + новой топологии.

    Args:
        raw: текущий raw-dict рецепта (из ``RecipeStore.read_raw``).
        blueprint: новый blueprint (``{name?, description?, processes, wires, displays}``);
            displays ДОЛЖНЫ лежать внутри blueprint (single source — ``blueprint.displays``).
            Позиции узлов — только внутри ``blueprint.metadata.gui_positions`` (их кладёт
            вызывающий); top-level ``gui_positions`` больше не пишется (AU-1).

    Pre:
      - raw — dict (копируется, не мутируется).
    Post:
      - результат — копия raw без ключей ``data``/``meta``/``gui_positions``,
        с ``blueprint`` = переданному.

    Returns:
        Новый dict (копия raw) с обновлёнными top-level секциями, без ``data``/``meta``
        и без legacy top-level ``gui_positions``.
    """
    result = dict(raw)
    result.pop("data", None)  # legacy-envelope от старой порчи — выкидываем
    result.pop("meta", None)
    # legacy top-level дубль позиций: канонические лежат в blueprint.metadata,
    # top-level никто не читает (аудит Ф4.8, AU-1) — вычищаем на запись.
    result.pop("gui_positions", None)
    result["blueprint"] = blueprint
    return result
