# recipe — Статус модуля

## Текущий этап: консолидация C3 закрыта (constructor-master Ф5-добор)

Крыша над управлением рецептами: `RecipeEngine` + `RecipeManager` + `is_v3_recipe` +
`normalize_recipe_v3_raw` + реестр step-миграций (`migration`/`registered_steps`/
`run_chain`) + единая «форма» v3-blueprint (`has_top_level_blueprint`/
`nested_blueprint_data`) + generic comment-preserving writer (`yaml_io`) сведены в
один framework-модуль. Доменные пути и миграции инжектируются (ADR-RCP-001/003/005).

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Движок ~360 LOC, менеджер ~320 LOC, migrations.py ~120 LOC |
| Тесты (покрытие) | 9 | Contract + detect + migrations (property round-trip) + yaml_io (home 7) + engine doc_type-wiring (6); прототип зелёный через шимы |
| Документация (README, interfaces) | 9 | README + interfaces.py (3 Protocol, +doc_type) + DECISIONS (RCP-001..005) |
| Связанность (меньше = лучше) | 9 | Store через StoreProtocol → нет импорта state_store (нет цикла) |
| Дублирование | 9 | `"blueprint" in raw` унифицирован (C2); yaml-writer сведён в модуль (C3); duplicate() через единый detect |
| Работоспособность | 9 | Зона recipe+recipes+backend+assembly 214 passed; снапшот 5.1 зелёный; frontend recipes+pipeline 598 passed |

## Границы задачи

- **C1 (сделано):** структурная консолидация + module-contract + инъекция путей/writer.
- **C2 (сделано, ADR-RCP-003):** реестр `@migration`/`run_chain` + единый detect формата
  (`has_top_level_blueprint`/`nested_blueprint_data`, call-sites переведены) +
  property-тесты round-trip (идемпотентность, сохранение неизвестных ключей).
- **C3 (сделано, ADR-RCP-005):** `yaml_io` → модуль (прототип — шим); снят seam
  RecipeManager (comment-preserving writer по умолчанию, `recipes/manager.py` → реэкспорт,
  отменяет ADR-RCP-002); `duplicate()` через detect-стратегию формата (`is_v3_recipe`);
  **run_chain — дефолт миграции RecipeEngine** (`doc_type` в `__init__`+Protocol; явный
  `migration_fn` приоритетен). Инъекция callbacks (ADR-SS-003) остаётся рабочим механизмом.
  **assembler/planner НЕ вынесены** — топология, дом `process_manager/topology` (ADR-RCP-005).

## Осталось в прототипе (по слою — доменное)

- Доменные миграции (`recipes/migrations/format_v1_to_v2.py`,
  `backend/state/recipes/migrations/v1_to_v2.py`) — знают схемы Inspector
  (cameras/regions/topology), зарегистрированы в реестре под своим `doc_type`
  (`recipe.file_format` / `recipe.config_snapshot`), инжектируются через callbacks.
- `recipes/devices_sync.py` — доменная синхронизация устройств.

## Смежный хвост (не recipe)

- Физперенос `assembler`/`planner` из `backend/assembly/` → `process_manager/topology`
  (ADR-RCP-005) — отдельная process_manager-задача (ноль новых межмодульных рёбер).
