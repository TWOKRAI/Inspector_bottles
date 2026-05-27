---
name: RecipesManager (RecipeEngine v2) state
description: Менеджер рецептов-blueprint'ов в прототипе; replace_blueprint с rollback
type: project
---

RecipeEngine (`multiprocess_framework`) + application-обёртка `RecipesManager` (`multiprocess_prototype/recipes/manager.py`).

Ключевые решения:
- Recipe = `SystemBlueprint` + параллельные yaml-секции `active_services` и `display_bindings` (ADR-131); blueprint остаётся generic
- `replace_blueprint` с snapshot+rollback при partial failure (ADR-132, ADR-PM-009)
- Формат v1→v2 миграция: `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py`
- Кнопка «Запустить активный рецепт» в RecipesTab вызывает `replace_blueprint` (коммит `da227903`)

## Связанные ADR / коммиты
- ADR-131 (SystemBlueprint generic + параллельные секции) — `multiprocess_framework/DECISIONS.md`
- ADR-132 (replace_blueprint с snapshot+rollback) — `multiprocess_framework/DECISIONS.md`
- ADR-PM-009 — `multiprocess_framework/modules/process_manager_module/DECISIONS.md`
- Phase 5 DONE: коммит `506308a1`
- Кнопка «Запустить»: коммит `da227903`

## Ключевые пути
- `multiprocess_prototype/recipes/` — yaml-рецепты (данные)
- `multiprocess_prototype/recipes/manager.py` — application-обёртка над RecipeEngine
- `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` — миграция
- `multiprocess_prototype/backend/state/adapters/recipe_adapter.py`
- `multiprocess_prototype/frontend/widgets/tabs/recipes/` — RecipesTab MVP

## Статус
Phase 5 DONE (2026-05-27). Stable. replace_blueprint протестирован с rollback-сценариями.
