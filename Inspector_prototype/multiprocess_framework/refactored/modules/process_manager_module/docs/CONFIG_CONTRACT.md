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
| `config` | dict | `model_dump()` конфига процесса | ProcessConfigHandler в process_module |
| `memory` | dict | SharedMemory: `{name: (h, w, c), "coll": N}` | process_runner нормализует в полный формат |
| `managers` | dict | Конфиг менеджеров (logger, error, stats, router) | ProcessSpawner при инициализации процесса |

## Поток данных

```
App Config (CameraConfig, etc.)
    → config.build() / process()
    → (name, proc_dict)
    → launcher.add_process(name, proc_dict)
    → merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
    → ProcessSpawner
```

## Источник правды

- **config_to_dict** (data_schema_module) — единственная реализация HasBuild → (name, dict)
- **ProcessSchemaAdapter** — делегирует в config_to_dict при наличии build()
- **DEFAULT_PROCESS_SCHEMA** (launcher/schema.py) — эталонная структура для нормализации
