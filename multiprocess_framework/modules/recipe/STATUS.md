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

## Шимы recipe-оси — план снятия (AU-7, follow-up В1, 2026-07-12)

Мёртвые реэкспорты `_flatten`/`_remap_path` в state_store-шиме
(`state_store_module/recipes/recipe_engine.py`) сняты (0 импортёров). Остальные шимы
recipe-оси имеют реальных импортёров — снимать рано, план снятия ниже (паттерн
QUEUE «Открытые решения» №4: снятие шима = 0 импортёров):

| Шим | Импортёров | Кто | Что нужно для 0 |
|-----|-----------|-----|------------------|
| `multiprocess_prototype/recipes/yaml_io.py` (→ `recipe.yaml_io`) | 5 | prod: `adapters/stores/recipe_store.py`, `recipes/migrations/displays_to_recipe.py`, `recipes/migrations/drop_display_name.py`; test: `recipes/tests/test_yaml_io.py`, `frontend/widgets/tabs/services/devices_common/tests/test_recipe_devices.py` | Перевести 3 prod call-sites на прямой импорт `multiprocess_framework.modules.recipe.yaml_io`; 2 теста — следом. Тело шима не трогать, только call-sites |
| `multiprocess_prototype/recipes/manager.py` (→ `recipe.manager.RecipeManager`) | 8 | prod: `frontend/app.py`, `frontend/widgets/tabs/recipes/recipe_io.py`, `adapters/stores/recipe_store.py`; test: `adapters/tests/test_integration_assembly.py`, `adapters/tests/test_recipe_store.py`, `recipes/tests/test_demo_recipe.py`, `recipes/tests/test_recipes_integration.py`, `recipes/tests/test_recipe_manager.py` | Перевести 3 prod call-sites на прямой импорт `multiprocess_framework.modules.recipe.manager.RecipeManager`; 5 тестов — следом |
| `state_store_module/recipes/recipe_engine.py` (→ `recipe.recipe_engine.RecipeEngine`) | 4 (все тесты, prod-путей нет) | `backend/state/recipes/tests/test_recipe_engine_wrapper.py`, `recipes/tests/test_demo_recipe.py`, `recipes/tests/test_recipe_manager.py`, `recipes/tests/test_recipes_integration.py` | Только тесты → перевести на прямой импорт `multiprocess_framework.modules.recipe.recipe_engine.RecipeEngine`, путь к 0 короче — нет prod-зависимости |

Оба `recipes/*.py`-шима идут через общий узел `adapters/stores/recipe_store.py` (импортирует
и `yaml_io`, и `manager`) — перевод этого файла закрывает большую часть prod-импортёров сразу.

## Смежный хвост (не recipe)

- Физперенос `assembler`/`planner` из `backend/assembly/` → `process_manager/topology`
  (ADR-RCP-005) — отдельная process_manager-задача (ноль новых межмодульных рёбер).
