# recipe — Статус модуля

## Текущий этап: консолидация C1 (constructor-master Ф5-добор)

Крыша над управлением рецептами: `RecipeEngine` + `RecipeManager` + `is_v3_recipe` +
`normalize_recipe_v3_raw` сведены в один framework-модуль. Доменные пути и миграции
инжектируются (ADR-RCP-001/002).

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Перенос устоявшегося кода; движок ~360 LOC, менеджер ~320 LOC |
| Тесты (покрытие) | 9 | Contract-тесты модуля + перенесённый test_recipe_engine; прототип зелёный через шимы |
| Документация (README, interfaces) | 9 | README + interfaces.py (3 Protocol) + DECISIONS (RCP-001/002) |
| Связанность (меньше = лучше) | 9 | Store через StoreProtocol → нет импорта state_store (нет цикла) |
| Дублирование | 7 | Временный дубль yaml-writer (fallback vs prototype ruamel) — снимается в C3 |
| Работоспособность | 9 | Базовая линия recipe-тестов сохранена; снапшот 5.1 зелёный |

## Границы задачи

- **C1 (сделано):** структурная консолидация + module-contract + инъекция путей/writer.
- **C2 (следующее):** реестр `@migration` + property-тесты round-trip. Сейчас миграция
  подключается callbacks-ами (ADR-SS-003), реестра нет.
- **C3 (следующее):** consolidation `yaml_io`/assembler + переработка `duplicate()`
  через generic yaml_io (убрать инъекцию-seam ADR-RCP-002).

## Осталось в прототипе (по слою — доменное/скоуп C2-C3)

- Доменные миграции (`recipes/migrations/format_v1_to_v2.py`,
  `backend/state/recipes/migrations/v1_to_v2.py`) — знают схемы Inspector
  (cameras/regions/topology), инжектируются через callbacks.
- `recipes/yaml_io.py` (`update_yaml_preserving`, `update_blueprint_metadata_preserving`)
  — широко используемая инфраструктура (app.yaml, launch, recipe_store); перенос = C3.
- `recipes/devices_sync.py` — доменная синхронизация устройств.
