"""recipe_format_hook.py — формат рецепта Inspector для ``RecipeService`` (Task 1b.1).

Реализация ``RecipeFormatHook`` (``multiprocess_framework/modules/recipe/service.py``)
из существующих кусков прототипа — ничего не копирует:

* ``normalize`` — существующие миграции ``recipes/migrations/``: v1
  (``topology:``-рецепт) → ``migrate_v1_to_v2``; v3 (top-level ``blueprint``) →
  ``canonicalize_gui_positions``. Сырая топология (``processes:`` сверху) — как есть.
* ``validate`` — ``validate_recipe_blueprint`` (тот же gate, что у Save в GUI),
  исключения переведены в ``[{"path", "message"}]``.
* ``to_topology`` — ПОЛНОЕ нормализованное тело, как его шлёт GUI в
  ``topology.apply``: хаб разворачивает рецепт сам (``orchestrator_hooks``) и
  берёт ``devices:`` из сырого тела (S-25). Развёртка здесь (``unwrap_recipe``)
  срезала бы ``devices:`` — найдено ревью 1b.1.

Qt-free: хук живёт на хабе.
"""

from __future__ import annotations

import copy
from typing import Any

from multiprocess_framework.modules.recipe.detect import has_top_level_blueprint

from multiprocess_prototype.recipes.migrations.canonicalize_gui_positions import canonicalize_gui_positions
from multiprocess_prototype.recipes.migrations.format_v1_to_v2 import is_v1_recipe, migrate_v1_to_v2
from multiprocess_prototype.recipes.save import RecipeValidationError, validate_recipe_blueprint


class InspectorRecipeFormatHook:
    """Формат рецепта Inspector: миграции → валидация → развёртка в топологию."""

    def normalize(self, body: dict) -> dict:
        if has_top_level_blueprint(body):
            return canonicalize_gui_positions(body)
        # v1 — только рецепт с ``topology:``; сырая топология (``processes:``) без
        # ``version`` тоже «v1» по is_v1_recipe, но мигрировать её нельзя.
        if "topology" in body and "processes" not in body and is_v1_recipe(body):
            return canonicalize_gui_positions(migrate_v1_to_v2(body))
        return copy.deepcopy(body)

    def validate(self, body: dict) -> list[dict]:
        if has_top_level_blueprint(body):
            target: Any = body["blueprint"]
            prefix = "blueprint"
        else:
            target, prefix = body, ""
        if not isinstance(target, dict):
            return [{"path": prefix, "message": f"ожидался mapping, получено {type(target).__name__}"}]
        try:
            validate_recipe_blueprint(target)
        except RecipeValidationError as exc:
            return [{"path": prefix, "message": str(msg)} for msg in exc.errors]
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError и пр.: контракт «не бросать»
            errors = getattr(exc, "errors", None)
            if callable(errors):
                try:
                    return [
                        {
                            "path": ".".join(p for p in (prefix, *map(str, e.get("loc", ()))) if p),
                            "message": str(e.get("msg", "")),
                        }
                        for e in errors()
                    ]
                except Exception:  # noqa: BLE001
                    pass
            return [{"path": prefix, "message": f"{type(exc).__name__}: {exc}"}]
        return []

    def to_topology(self, body: dict) -> dict:
        return copy.deepcopy(body)
