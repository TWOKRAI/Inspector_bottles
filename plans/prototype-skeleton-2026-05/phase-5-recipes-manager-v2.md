# Phase 5 — Recipe Manager + replace_blueprint

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/recipes-manager-v2`
> **Дней**: 7-10
> **Зависимости**: Phase 2 (paths), Phase 3 (services), Phase 4 (displays)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

Рецепт = полноценный blueprint. RecipesTab переписан с slot-based на менеджер blueprints. Переключение активного рецепта вызывает `ProcessManager.replace_blueprint()` (рабочие процессы перезапускаются, GUI и orchestrator живут).

## Реальная фундация

- `RecipeEngine` — **уже в framework** (`state_store_module/recipes/recipe_engine.py`, 369 строк). Используем существующий API.
- `SystemBlueprint` (Phases 0-2 done в config_driven_arch) — валидируемый yaml.
- `ProcessManagerProcess` — есть `stop/restart` для одного процесса, **нет** `replace_blueprint`. **Нужен новый метод**.
- Текущий `RecipesPresenter` — slot-based (8 жёстких слотов, recipe = topology snapshot). Полностью переписать.

## Структура нового рецепта (`multiprocess_prototype/recipes/<slug>.yaml`)

```yaml
version: 2
name: cup_inspection
description: Контроль чашек на конвейере
created: 2026-05-24
modified: 2026-05-24
blueprint:                  # стандартный SystemBlueprint (framework) — никаких новых полей
  processes: [...]
  wires: [...]
active_services: [webcam_camera]      # application-секция, ВНЕ SystemBlueprint
display_bindings:                     # application-секция, ВНЕ SystemBlueprint
  - source: merge_proc.render_overlay.out
    display: main_output
  - source: capture_proc.resize.out
    display: debug_input
```

**Важно**: `active_services` и `display_bindings` — Inspector-специфичные секции, существующие **рядом** с blueprint, а не внутри него. SystemBlueprint остаётся generic-контрактом framework (processes + wires + name + description). ADR в `multiprocess_framework/DECISIONS.md`: «SystemBlueprint остаётся generic; application-расширения рецепта живут параллельными секциями yaml».

## Миграция со старого формата

- v1: `recipe_N.yaml` с `{name, description, topology}` (8 жёстких слотов).
- v2: `recipe_<slug>.yaml` с `{version, name, description, blueprint, active_services, display_bindings}`.
- **Новая** `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` (пишем с нуля, ~100 строк) — конвертирует topology dict в blueprint + извлекает display_bindings из старых wires `*.display.*` + active_services из используемых сервисов. **Внимание**: миграция `v1_to_v2.py` из backup — это **другая** миграция (внутренняя структура рецепта `processing_blocks → nodes`), не путать.
- Регистрируется в `RecipeEngine` через стандартный механизм (existing API).
- При первом запуске после Phase 5 — миграция всех `data/recipes/recipe_*.yaml` в `recipes/<slug>.yaml`.

## Новое

- `multiprocess_prototype/recipes/manager.py` — `RecipeManager` (тонкая application-обёртка над framework `RecipeEngine`):
  - `load/save/list/duplicate/delete/set_active`.
  - Persist в `recipes/<slug>.yaml`. Активный = `state.recipes.active` (StateProxy).
- `multiprocess_prototype/recipes/migrations/format_v1_to_v2.py` — новая миграция формата (см. выше).
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — **новый метод** `replace_blueprint(new_blueprint: SystemBlueprint)`:
  - Список процессов, помеченных `protected=true` — НЕ трогаем.
  - Список остальных — `stop` + cleanup SHM-сегментов + recreate из нового blueprint + start.
  - Rollback при partial failure (если новый процесс не стартовал — вернуть старый blueprint).
- `multiprocess_prototype/backend/state/adapters/recipe_adapter.py` — из backup, адаптирован.
- `multiprocess_prototype/registers/manager.py` — расширить `build_rm_from_topology()`:
  - Базовый слой: всегда подгружать из `multiprocess_prototype/registers/*.yaml` (если есть).
  - Active-слой: регистры плагинов/сервисов из активного рецепта.
- Расширить StateStore bootstrap: `state.recipes.*` (список + active).
- ADR в `multiprocess_framework/DECISIONS.md`: «Recipe = SystemBlueprint v2, replace_blueprint в ProcessManager».

## RecipesTab

- Переписать `tabs/recipes/tab.py` и presenter с slot-based на менеджер:
  - Левая колонка: список рецептов из `recipes/*.yaml` (динамический, не 8 фиксированных).
  - Правая панель: метаданные + сводка blueprint (процессы, плагины, дисплеи, активные сервисы) + список регистров.
  - Кнопки: «Создать новый» (пустой шаблон), «Дублировать», «Удалить», «Сделать активным», «Открыть в Pipeline».
- При смене активного → `ProcessManager.replace_blueprint(new)` → PipelineTab перерисовывает граф.

## Acceptance

- Старые `recipe_N.yaml` смигрированы в новый формат при первом запуске.
- Создали 2 рецепта (`cup_inspection`, `bottle_inspection`) с разными цепочками; переключение перезапускает worker-процессы (GUI и orchestrator живые); регистры перестраиваются; PipelineTab показывает новый граф.
- 30-40 unit-тестов: RecipeManager CRUD, миграция v1→v2, replace_blueprint (включая partial failure rollback), state adapter.
