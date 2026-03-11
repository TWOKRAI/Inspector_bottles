# Анализ: единый подход к конфигам (Dict at Boundary)

## Текущее состояние

### 1. Поток данных конфигов

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  App (main.py, multiprocess_prototype)                                        │
│  Process1Config(), Worker1Config() — RegisterBase из data_schema_module      │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ add_process(config, workers)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  SystemLauncher (process_manager_module)                                     │
│  ИМПОРТ: RegisterBase из data_schema_module                                 │
│  Типы: config: Union[ProcessBuilder, RegisterBase, Dict]                    │
│  Конвертация: build() / to_dict() → (name, proc_dict)                        │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ processes_config: Dict
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ProcessSpawner, ProcessManagerProcess, ProcessRegistry                       │
│  Работают ТОЛЬКО с dict — без data_schema_module                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Модули и их зависимости от data_schema

| Модуль | Импортирует data_schema? | Принимает config как |
|--------|--------------------------|----------------------|
| **process_manager/launcher/system_launcher** | Да (RegisterBase) | ProcessBuilder, RegisterBase, dict |
| **process_manager/launcher/spawner** | Нет | dict (processes_config) |
| **process_manager/process/process_manager_process** | Нет | dict (из bundle) |
| **process_manager/core/process_registry** | Нет | dict |
| **error_module/core/error_manager** | Нет | dict, LogConfig, object с build() |
| **error_module/config/error_config** | Да | — (определяет конфиг) |
| **logger_module** | Нет | LogConfig (свой dataclass) |
| **config_module** | Да (StorageManager) | dict |

### 3. Контракт build()

**Единый контракт:** `build() -> tuple[str, dict]`

- Process1Config.build() → ("process_1", {"class": "...", "queues": {...}})
- Worker1Config.build() → ("worker_1", {...})
- ErrorManagerConfig.build() → ("ErrorManager", {"app_name": "errors", ...})

### 4. Несогласованности

| Проблема | Где | Решение |
|----------|-----|---------|
| SystemLauncher импортирует RegisterBase | system_launcher.py | Убрать импорт, использовать Protocol или duck typing |
| ProcessBuilder требует RegisterBase в типах | ProcessBuilder.__init__, add_worker | Заменить на "object с build()" |
| create_process(config: RegisterBase) | SystemLauncher | Заменить на Union[Dict, HasBuild] |
| workers: List[RegisterBase] | add_process | Заменить на List[HasBuild] или List[Any] |

---

## Рекомендуемый единый подход

### Принцип: Dict at Boundary

1. **data_schema_module** — точка истины для ОПРЕДЕЛЕНИЯ конфигов (RegisterBase, FieldMeta, register_schema).
2. **Модули фреймворка** (process_manager core, error_manager core, spawner) — принимают только **dict** или объект с **build() -> (name, dict)**.
3. **Импорт data_schema** — только в слое конфигов (config/, app processes/).

### Контракт для потребителей конфига

```python
# Протокол (опционально, для типизации)
from typing import Protocol

class HasBuild(Protocol):
    def build(self) -> tuple[str, dict]: ...

# Модуль принимает:
config: Union[dict, HasBuild, None]
```

### Правила

1. **Определение конфига** — в app или в config/ модуля. Использует RegisterBase.
2. **Потребление конфига** — модуль проверяет `hasattr(config, "build")` и вызывает `config.build()`, либо принимает dict напрямую.
3. **Без импорта RegisterBase** в consumer-модулях.

---

## План унификации

### Шаг 1: process_manager_module/launcher/system_launcher.py

- Удалить `from ...data_schema_module import RegisterBase`
- Заменить типы:
  - `ProcessBuilder.__init__(self, config: Any)` — любой объект с `build()`
  - `add_worker(self, config: Any)` — любой объект с `build()`
  - `create_process(self, config: Union[Dict, Any])` — dict или build()
  - `workers: Optional[List[Any]]` — список объектов с `build()`
- Логика уже использует duck typing (`hasattr(config, "build")`) — меняются только аннотации.

### Шаг 2: Документировать контракт

- В README process_manager_module: "config должен иметь build() -> (name, dict) или быть dict".
- В README error_module: уже описано.
- Общий документ: CONFIG_CONTRACT.md с примером.

### Шаг 3: LoggerManager (опционально)

- Сейчас принимает только LogConfig.
- Для единообразия: добавить приём dict и object с build() по аналогии с ErrorManager.
- Или оставить как есть — LoggerManager не использует RegisterBase.

### Шаг 4: config_module

- ConfigManager использует data_schema для StorageManager, не для типов конфига.
- Оставить без изменений или вынести StorageManager в отдельный слой.

---

## Итоговая схема

```
┌──────────────────────────────────────────────────────────────────┐
│  data_schema_module (точка истины)                                │
│  RegisterBase, FieldMeta, register_schema                        │
└─────────────────────────────┬────────────────────────────────────┘
                              │ только в config-слое
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  Config-слой (app, error_module/config, process configs)          │
│  Process1Config, ErrorManagerConfig — RegisterBase               │
│  build() -> (name, dict)                                         │
└─────────────────────────────┬────────────────────────────────────┘
                              │ передаём dict или объект с build()
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  Framework modules (БЕЗ импорта data_schema)                      │
│  SystemLauncher, ErrorManager, ProcessSpawner                    │
│  Принимают: dict | object с build() | None                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## Оценка как тимлид: 9/10 (с default_schema)

**Плюсы подхода:**
- Меньше связей между модулями
- Единый контракт build() -> (name, dict)
- Гибкость: можно передать dict из YAML/JSON без RegisterBase
- Тестирование проще — моки как dict
- **default_schema в consumer** — каждый модуль определяет ожидаемый формат, merge_with_defaults заполняет недостающие ключи

**Риски:**
- Потеря строгой типизации на границе (компенсировано Protocol HasBuild)
- Нужно поддерживать контракт dict (документация, DEFAULT_PROCESS_SCHEMA)

---

## Реализовано

- **Dict at Boundary** — SystemLauncher принимает только (name, proc_dict)
- **process()** — алиас build_process_with_workers в data_schema_module
- **HasBuild** — Protocol для типизации конфигов
- **DEFAULT_PROCESS_SCHEMA** — в process_manager_module/launcher/schema.py
- **merge_with_defaults** — нормализация proc_dict при add_process()
