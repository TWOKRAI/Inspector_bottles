# План унификации конфигов фреймворка

**Версия:** 1.0  
**Дата:** 2026-04-20  
**Статус:** draft — ожидает утверждения  
**Цель:** Один механизм конфигурации для всех модулей фреймворка. Обратная совместимость с v1/v2/v3.

---

## 1. Текущая архитектура (as-is)

### Два уровня конфигов

В фреймворке сосуществуют **два независимых механизма**, которые путаются:

| Уровень | Что | Где живёт | Назначение |
|---------|-----|-----------|------------|
| **Schema** | `SchemaBase` (Pydantic) + `@register_schema` | `data_schema_module` | Статическое описание: поля, типы, валидация, FieldMeta |
| **Runtime** | `Config` + `ConfigManager` + `ConfigSection` | `config_module` | Динамический контейнер: RLock, dot-notation, env fallback, subscriptions |

**Проблема:** Все 37 конфиг-классов модулей наследуют `SchemaBase` напрямую из `data_schema_module`, а НЕ из `config_module`. `config_module` используется только для runtime (ConfigStore, ProcessConfigHandler). Нет единого "конфигурационного слоя" — есть слой данных + слой runtime, но модули знают только о слое данных.

### Конфиг-классы по модулям (37 классов, ~1400 строк)

```
SchemaBase (data_schema_module)
├── BaseManagerConfig                    (base_manager/configs/)
├── ChannelRoutingConfig                 (channel_routing_module/core/)
│   ├── LoggerManagerConfig              (logger_module/configs/, 192 стр)
│   │   └── вложенные: LoggerChannelSchema, LoggerScopeSchema, LoggerModuleSchema
│   ├── StatsManagerConfig               (statistics_module/configs/, 62 стр)
│   └── ChannelRoutingManagerConfig      (channel_routing_module/configs/)
├── RouterManagerConfig                  (router_module/configs/)
├── CommandManagerConfig                 (command_module/configs/)
├── DispatcherConfig                     (dispatch_module/configs/)
├── ErrorManagerConfig                   (error_module/configs/)
├── ConsoleConfig                        (console_module/configs/)
├── ConsoleProcessConfig                 (console_module/configs/)
├── FrontendManagerConfig                (frontend_module/configs/)
│   └── вложенные: WindowManagerConfig, ThreadManagerConfig
├── ProcessLaunchConfig                  (process_module/configs/, 96 стр)
├── ManagersConfig                       (process_module/configs/, 174 стр)
│   └── композиция: logger, error, stats, router, command, console
├── SharedResourcesManagerConfig         (shared_resources_module/configs/)
├── SQLManagerConfig                     (sql_module/configs/)
├── ThreadWorkerConfig                   (worker_module/configs/)
├── WorkerManagerConfig                  (worker_module/configs/)
└── ConfigManagerConfig                  (config_module/configs/)
```

### Паттерны (что уже хорошо работает)

1. **Colocation** — конфиг рядом с модулем (`logger_module/configs/logger_manager_config.py`)
2. **Blueprint Factory** — `_LOGGER_BLUEPRINT.model_copy(deep=True)` предотвращает shared mutation
3. **Composition** — `ManagersConfig` агрегирует 6 менеджер-конфигов через Pydantic Fields
4. **Merge** — `merge_managers(base, overlay)` для глубокого слияния
5. **Build** — `ProcessLaunchConfig.build()` → `(name, proc_dict)` для SystemLauncher
6. **Normalization** — `normalize_managers_view()` обрабатывает legacy/modern форматы

### Использование в прототипах

| Версия | Base class | Как инстанциируют | Managers |
|--------|-----------|-------------------|----------|
| **v1** | `ProcessConfigBase(SchemaBase)` — кастомная обёртка | `CameraConfig(camera_type=...)` → `launcher.add_process(*process(cfg))` | `get_default_managers_config()` → dict |
| **v2** | `ProcessConfigBase(SchemaBase)` — та же обёртка | то же + `ManagersConfigLite` (alias на `ManagersConfig`) | `build_default_managers_model()` → `ManagersConfig` |
| **v3** | `ProcessLaunchConfig` — напрямую из framework | `AppConfig(camera=CameraConfig(...))` → `app.all_process_configs()` | Встроено в `ProcessLaunchConfig.build()` |

---

## 2. Оценка: централизация vs colocation

### Аргументы за централизацию (все конфиги в config_module/)

| За | Против |
|----|--------|
| Одно место для всех конфиг-классов | Модули теряют автономность — нельзя взять модуль отдельно |
| Нет circular imports | Появляется god-module, который знает о всех модулях |
| Единая точка документации | Нарушает принцип "конфиг рядом с кодом, который его использует" |
| | Массовый рефакторинг всех импортов во всех прототипах |

### Аргументы за colocation (конфиг рядом с модулем)

| За | Против |
|----|--------|
| Модуль = самодостаточная единица (переносимость) | Нет единого обзора всех конфигов |
| Конфиг меняется вместе с модулем | Каждый модуль сам определяет свой "стандарт" |
| Минимальный coupling | Нужен общий базовый класс, но его нет |
| Уже работает в v1/v2/v3 | |

### Вердикт: **Colocation + unified base + registry**

Централизация конфиг-классов — это god-module антипаттерн. Текущая colocation правильна по принципу. Но не хватает:

1. **Единого базового класса для конфигов менеджеров** (сейчас все наследуют голый SchemaBase)
2. **Автоматического реестра конфигов** (сейчас `@register_schema` — это реестр *схем*, не *конфигов*)
3. **Стандартного интерфейса** для manager config (name, enabled, validate_for_process)
4. **Единой точки сборки** — ProcessLaunchConfig знает о ManagersConfig, но других путей нет

---

## 3. План унификации

### Фаза 0 — Базовый класс ManagerConfig (config_module)

**Цель:** Все конфиги менеджеров наследуют от `ManagerConfig` вместо голого `SchemaBase`.

**Файлы:**
- `config_module/configs/manager_config.py` — **новый** базовый класс
- `config_module/configs/__init__.py` — экспорт

```python
# config_module/configs/manager_config.py
from data_schema_module import SchemaBase, register_schema

class ManagerConfig(SchemaBase):
    """Базовый конфиг для любого менеджера фреймворка.
    
    Наследники:
    - LoggerManagerConfig
    - ErrorManagerConfig
    - StatsManagerConfig
    - RouterManagerConfig
    - CommandManagerConfig
    - ConsoleConfig
    - и т.д.
    """
    manager_name: str = ""       # Имя менеджера (если нужно переопределить)
    enabled: bool = True         # Можно ли отключить менеджер
    
    def validate_for_process(self, process_name: str) -> list[str]:
        """Валидация конфига в контексте конкретного процесса.
        Возвращает список ошибок (пустой = ок).
        Переопределяется в наследниках при необходимости.
        """
        return []
```

**Объём:** ~30 строк нового кода + правки наследования в 10 модулях.

**Миграция наследования:**
```
До:  class LoggerManagerConfig(ChannelRoutingConfig)   # ChannelRoutingConfig(SchemaBase)
После: class LoggerManagerConfig(ChannelRoutingConfig)  # ChannelRoutingConfig(ManagerConfig)
                                                        # ManagerConfig(SchemaBase)
```

Для модулей, которые наследуют `SchemaBase` напрямую:
```
До:  class RouterManagerConfig(SchemaBase)
После: class RouterManagerConfig(ManagerConfig)
```

**Обратная совместимость:** 100%. `ManagerConfig` наследует `SchemaBase`, добавляет optional поля с defaults. Все существующие инстанциации продолжают работать.

### Фаза 1 — ConfigRegistry (config_module)

**Цель:** Автоматический реестр всех конфигов менеджеров. Одна точка, где можно узнать "какие менеджеры существуют и какие у них конфиги".

**Файлы:**
- `config_module/core/config_registry.py` — **новый**
- `config_module/__init__.py` — экспорт

```python
# config_module/core/config_registry.py
from typing import Type

_MANAGER_CONFIGS: dict[str, Type["ManagerConfig"]] = {}

def register_manager_config(name: str):
    """Декоратор: регистрирует конфиг менеджера в глобальном реестре."""
    def decorator(cls):
        _MANAGER_CONFIGS[name] = cls
        return cls
    return decorator

def get_manager_config_class(name: str) -> Type["ManagerConfig"] | None:
    return _MANAGER_CONFIGS.get(name)

def list_manager_configs() -> dict[str, Type["ManagerConfig"]]:
    return dict(_MANAGER_CONFIGS)
```

**Использование в модулях:**
```python
# logger_module/configs/logger_manager_config.py
from config_module import ManagerConfig, register_manager_config

@register_manager_config("logger")
@register_schema("logger_manager")
class LoggerManagerConfig(ChannelRoutingConfig):
    ...
```

**Объём:** ~40 строк нового кода + добавить декоратор в ~10 модулей (1 строка на модуль).

**Зачем:** `ManagersConfig` сейчас хардкодит 6 менеджеров. С реестром — можно собирать managers payload динамически. Это важно для расширяемости (новый модуль = новый менеджер = автоматически в реестре).

### Фаза 2 — ManagersConfig v2 (process_module)

**Цель:** `ManagersConfig` использует `ConfigRegistry` вместо хардкода полей.

**Текущий хардкод:**
```python
class ManagersConfig(SchemaBase):
    logger: LoggerManagerConfig = Field(default_factory=_default_logger)
    error: ErrorManagerConfig = Field(default_factory=_default_error)
    stats: StatsManagerConfig = Field(default_factory=_default_stats)
    router: RouterManagerConfig = Field(default_factory=_default_router)
    command: CommandManagerConfig = Field(default_factory=_default_command)
    console: ConsoleConfig = Field(default_factory=_default_console)
```

**Варианты:**

**A) Мягкая миграция (рекомендую):**
Оставить существующие поля, но добавить fallback на реестр:
```python
class ManagersConfig(SchemaBase):
    # Явные поля остаются для обратной совместимости
    logger: LoggerManagerConfig = Field(default_factory=_default_logger)
    error: ErrorManagerConfig = Field(default_factory=_default_error)
    # ...
    
    # Дополнительные менеджеры из реестра
    extra_managers: dict[str, ManagerConfig] = Field(default_factory=dict)
    
    def all_managers(self) -> dict[str, ManagerConfig]:
        """Все менеджеры: явные + из extra_managers."""
        result = {}
        for name in MANAGER_SECTION_KEYS:
            result[name] = getattr(self, name)
        result.update(self.extra_managers)
        return result
```

**B) Полная динамика (агрессивная, не рекомендую сейчас):**
Заменить все поля на `managers: dict[str, ManagerConfig]`. Ломает все существующие `managers.logger.app_name = "..."` обращения.

**Объём (вариант A):** ~20 строк в ManagersConfig + метод `all_managers()`.

### Фаза 3 — Унификация ProcessConfigBase → ProcessLaunchConfig

**Цель:** Один базовый класс для конфигов процессов.

**Текущая ситуация:**
- v1, v2: `ProcessConfigBase(SchemaBase)` — кастомная обёртка в каждом прототипе
- v3: `ProcessLaunchConfig` — напрямую из фреймворка

**План:**
1. Убедиться, что `ProcessLaunchConfig` покрывает все use cases из `ProcessConfigBase`
2. Добавить в `ProcessLaunchConfig` недостающие методы (если есть)
3. В v1/v2: `ProcessConfigBase = ProcessLaunchConfig` (alias) — deprecation warning

**Файлы:**
- `process_module/configs/process_launch_config.py` — возможные дополнения
- `multiprocess_prototype/backend/configs/base_config.py` — alias
- `multiprocess_prototype_v2/backend/configs/base_config.py` — alias

**Обратная совместимость:** Alias сохраняет все импорты. Прототипы не ломаются.

### Фаза 4 — Документация и guidelines

**Цель:** Разработчик нового модуля знает: "как создать конфиг для моего менеджера".

**Файлы:**
- `config_module/docs/CONFIG_GUIDE.md` — **новый** гайд:
  - Как создать конфиг менеджера
  - Как зарегистрировать в реестре
  - Как добавить в ManagersConfig
  - Как использовать в ProcessLaunchConfig
  - Шаблон конфига

---

## 4. Что НЕ переносить в config_module

| Класс | Где | Почему оставить |
|-------|-----|-----------------|
| `ProcessLaunchConfig` | process_module | Это process-domain, не config-domain |
| `ManagersConfig` | process_module | Композиция менеджеров — это про запуск процесса |
| `LoggerManagerConfig` | logger_module | Colocation — конфиг рядом с модулем |
| Все `*ManagerConfig` | свои модули | Colocation |
| `ChannelRoutingConfig` | channel_routing_module | Доменная логика каналов |

**В config_module переносится только:**
- `ManagerConfig` (базовый класс)
- `ConfigRegistry` (реестр менеджер-конфигов)
- `CONFIG_GUIDE.md` (документация)

---

## 5. Порядок выполнения

```
Фаза 0: ManagerConfig base class
   │     ~30 строк нового кода
   │     ~10 файлов: правка наследования (1 строка на файл)
   │     Риск: минимальный (добавление, не изменение)
   ▼
Фаза 1: ConfigRegistry
   │     ~40 строк нового кода
   │     ~10 файлов: добавить декоратор (1 строка на файл)
   │     Риск: минимальный (opt-in)
   ▼
Фаза 2: ManagersConfig v2 (вариант A)
   │     ~20 строк в ManagersConfig
   │     Риск: средний (затрагивает сборку managers payload)
   │     Тесты: managers_config → all_managers() → merge → build
   ▼
Фаза 3: ProcessConfigBase → ProcessLaunchConfig alias
   │     ~5 строк на прототип (alias + deprecation warning)
   │     Риск: низкий (alias, не breaking change)
   ▼
Фаза 4: Документация
         CONFIG_GUIDE.md + обновление MODULES_INDEX
```

**Общий объём:** ~120 строк нового кода + ~30 строк правок в существующих файлах.

---

## 6. Что это даёт

| До | После |
|----|-------|
| Все конфиги наследуют голый `SchemaBase` — нет общего контракта | `ManagerConfig` — единый контракт: `enabled`, `validate_for_process()` |
| Хардкод 6 менеджеров в `ManagersConfig` | Реестр + `all_managers()` — расширяемость |
| `ProcessConfigBase` дублируется в v1/v2 | Один `ProcessLaunchConfig` + alias |
| Нет гайда "как создать конфиг" | `CONFIG_GUIDE.md` — шаблон + checklist |
| config_module почти не используется модулями | config_module — authority для config infrastructure |

---

## 7. Риски и миграция

| Риск | Митигация |
|------|-----------|
| Circular imports (config_module ← module configs) | config_module экспортирует только базовый класс, не знает о конкретных модулях |
| Сломать v1/v2 импорты | Alias `ProcessConfigBase = ProcessLaunchConfig` |
| ManagersConfig.all_managers() ломает merge | Фаза 2 — мягкая: явные поля остаются, extra_managers дополняет |
| Регрессия в build() / normalize | Тесты: запуск validate.py + run_framework_tests.py после каждой фазы |

---

## 8. Связанные документы

- `UNIFICATION_PLAN.md` (корень Inspector_prototype) — общий план унификации framework + App
- `config_module/interfaces.py` — IConfig, IConfigManager протоколы
- `process_module/configs/managers_config.py` — текущая композиция менеджеров
- `process_module/configs/process_launch_config.py` — текущий ProcessLaunchConfig
- `data_schema_module/` — SchemaBase, FieldMeta, @register_schema
