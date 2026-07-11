# recipe — Статус модуля

## Текущий этап: консолидация C2 (constructor-master Ф5-добор)

Крыша над управлением рецептами: `RecipeEngine` + `RecipeManager` + `is_v3_recipe` +
`normalize_recipe_v3_raw` + реестр step-миграций (`migration`/`registered_steps`/
`run_chain`) + единая «форма» v3-blueprint (`has_top_level_blueprint`/
`nested_blueprint_data`) сведены в один framework-модуль. Доменные пути и миграции
инжектируются (ADR-RCP-001/002/003).

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Движок ~360 LOC, менеджер ~320 LOC, migrations.py ~120 LOC |
| Тесты (покрытие) | 9 | Contract-тесты + test_detect (9) + test_migrations (26, property round-trip); прототип зелёный через шимы |
| Документация (README, interfaces) | 9 | README + interfaces.py (3 Protocol) + DECISIONS (RCP-001/002/003) |
| Связанность (меньше = лучше) | 9 | Store через StoreProtocol → нет импорта state_store (нет цикла) |
| Дублирование | 8 | `"blueprint" in raw` унифицирован (5→0 копий вне модуля, C2); yaml-writer дубль остаётся до C3 |
| Работоспособность | 9 | Базовая линия recipe-тестов сохранена; снапшот 5.1 зелёный; pipeline 564 passed |

## Границы задачи

- **C1 (сделано):** структурная консолидация + module-contract + инъекция путей/writer.
- **C2 (сделано, ADR-RCP-003):** реестр `@migration`/`run_chain` + единый detect формата
  (`has_top_level_blueprint`/`nested_blueprint_data`, call-sites переведены) +
  property-тесты round-trip (идемпотентность, сохранение неизвестных ключей).
  Инъекция callbacks (ADR-SS-003) сохранена как рабочий механизм — реестр стал
  дефолтным источником шагов, RecipeEngine на `run_chain` по умолчанию не переведён
  (потребовало бы public API change `RecipeEngineProtocol`, отложено).
- **C3 (следующее):** consolidation `yaml_io`/assembler + переработка `duplicate()`
  через generic yaml_io (убрать инъекцию-seam ADR-RCP-002).

## Осталось в прототипе (по слою — доменное/скоуп C3)

- Доменные миграции (`recipes/migrations/format_v1_to_v2.py`,
  `backend/state/recipes/migrations/v1_to_v2.py`) — знают схемы Inspector
  (cameras/regions/topology), зарегистрированы в реестре под своим `doc_type`
  (`recipe.file_format` / `recipe.config_snapshot`), инжектируются через callbacks.
- `recipes/yaml_io.py` (`update_yaml_preserving`, `update_blueprint_metadata_preserving`)
  — широко используемая инфраструктура (app.yaml, launch, recipe_store); перенос = C3.
- `recipes/devices_sync.py` — доменная синхронизация устройств.
