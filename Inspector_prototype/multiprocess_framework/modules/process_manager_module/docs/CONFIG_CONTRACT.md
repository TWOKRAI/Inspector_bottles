# Контракт proc_dict (add_process)

Структура `proc_dict`, передаваемого в `SystemLauncher.add_process(name, proc_dict)`.

## Обязательные поля (нормализуются через DEFAULT_PROCESS_SCHEMA)

| Поле | Тип | Описание |
|------|-----|----------|
| `class` | str | Полный путь к классу процесса (например, `my_module.MyProcess`) |
| `queues` | dict | Очереди: `{"system": {"maxsize": N}, "data": {"maxsize": M}, ...}` |
| `priority` | str | Приоритет: `high`, `normal`, `low`. Рекомендуется `ProcessPriorityLevel` (process_module) |
| `workers` | dict | Воркеры: `{worker_name: worker_dict}` или `{}` |

Недостающие ключи заполняются через `merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)`.

## Опциональные поля (приложение добавляет)

| Поле | Тип | Описание | Потребитель |
|------|-----|----------|-------------|
| `config` | dict | Полезная нагрузка процесса: часто `model_dump()` схемы (в т.ч. вложенный `managers` — см. `ManagersConfig`, `ProcessLaunchConfig`) | ProcessConfigHandler в process_module |
| `memory` | dict | SharedMemory: `{name: (h, w, c), "coll": N}` | process_runner нормализует в полный формат |
| `managers` | dict (опц.) | Секции менеджеров на верхнем уровне proc_dict (legacy / merge в `proc_assembly`-стиле) | Совместимость; в каноне SchemaBase секции часто только в `config.managers` |

`get_managers_config()` / `normalize_managers_view` в `process_module` приводят к одному виду: верхний `managers`, либо `config.managers`, либо плоские ключи секций (`logger`, `console`, …).

## Поток данных

```
App Config (CameraConfig, etc.)
    → config.build() / process()
    → (name, proc_dict)
    → launcher.add_process(name, proc_dict)
    → merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
    → ProcessSpawner
```

## Bundle (connection bundle для `run_process_function`)

Pickle-safe `dict`, собираемый в `ProcessRegistry` через `core/bundle_contract.build_bundle()` и разбираемый в `runner/bundle_builder._build_shared_resources_from_bundle()`.

| Ключ | Обязательность | Описание |
|------|------------------|----------|
| `queues` | да | Очереди текущего процесса `{type: Queue}` |
| `config` | да | Конфиг процесса (dict), в т.ч. `processes_config` для оркестратора |
| `custom` | нет | Данные `ProcessData.custom` без non-picklable (`stop_event` в bundle не кладётся — передаётся аргументом top-level функции) |
| `routing_map` | нет | Карта очередей по имени процесса для маршрутизации |

Проверка минимальной структуры: `validate_bundle(bundle)` (`queues` и `config` присутствуют).

## Источник правды

- **config_to_dict** (data_schema_module) — единственная реализация HasBuild → (name, dict)
- **ProcessSchemaAdapter** — делегирует в config_to_dict при наличии build()
- **DEFAULT_PROCESS_SCHEMA** (launcher/schema.py) — эталонная структура для нормализации

## Эталонные примеры в коде

См. [examples/proc_dict_canonical_examples.py](examples/proc_dict_canonical_examples.py) — готовые `proc_dict` и демонстрация `merge_with_defaults` (без импорта всего `process_manager_module`).
