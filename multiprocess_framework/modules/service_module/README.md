# service_module

## Назначение

`service_module` — framework-модуль реестра и управления метаданными long-running сервисов: камер, БД-подключений, auth-провайдеров и других объектов с явным жизненным циклом. В отличие от `PluginRegistry`, сервисы не поддерживают hot-reload и имеют расширенный lifecycle-автомат (`UNREGISTERED → READY → RUNNING → STOPPED → ERROR`).

Модуль является **generic-компонентом фреймворка** и не знает о конкретных реализациях из `Services/`, `Plugins/` или `multiprocess_prototype/`. Он предоставляет контракт (`IService`), реестр (`ServiceRegistry`), декоратор регистрации (`@register_service`) и сканер директорий (`scanner.discover`). Инстанцирование сервисов и управление жизненным циклом — ответственность application-слоя.

Inspector-приложение потребляет модуль через публичный API: bootstrap-код вызывает `scanner.discover(paths)`, после чего `ServiceRegistry().list()` доступен в `ServicesTab` и через `ServiceStateAdapter`.

## Структура модуля

```
service_module/
├── __init__.py        # Публичный API — реэкспорт ключевых имён
├── interfaces.py      # IService Protocol + ServiceLifecycle enum
├── registry.py        # ServiceRegistry singleton + ServiceEntry + @register_service
├── scanner.py         # discover(*dirs) + DiscoveryResult
├── README.md
├── STATUS.md
├── DECISIONS.md
└── tests/
    ├── __init__.py
    ├── test_registry.py  # 26 тестов
    └── test_scanner.py   # 15 тестов
```

## Публичный API

```python
from multiprocess_framework.modules.service_module import (
    IService,           # Protocol — контракт сервиса
    ServiceLifecycle,   # StrEnum — состояния жизненного цикла
    ServiceEntry,       # dataclass — запись в реестре
    ServiceRegistry,    # singleton — центральный каталог
    register_service,   # декоратор — точка регистрации
)
from multiprocess_framework.modules.service_module.scanner import (
    discover,           # функция — auto-discovery из файловой системы
    DiscoveryResult,    # dataclass — результат сканирования
)
```

### Таблица компонентов

| Компонент | Тип | Описание |
|-----------|-----|----------|
| `IService` | `@runtime_checkable Protocol` | Контракт: `name: str`, `start(config) -> bool`, `stop() -> bool`, `get_status() -> dict` |
| `ServiceLifecycle` | `StrEnum` | Состояния: `UNREGISTERED`, `READY`, `RUNNING`, `STOPPED`, `ERROR` |
| `ServiceEntry` | `dataclass` | Запись реестра: `name`, `cls`, `lifecycle`, `meta` |
| `ServiceRegistry()` | singleton | Реестр: `register`, `get`, `list`, `filter`, `unregister`, `clear` |
| `@register_service` | декоратор | Регистрирует класс в singleton при импорте; lifecycle становится `READY` |
| `discover(*dirs)` | функция | Рекурсивный поиск `service.py`, импорт через `importlib`, возврат `DiscoveryResult` |

## Быстрый старт

```python
# --- Регистрация сервиса (application-слой, например Services/my/service.py) ---
from multiprocess_framework.modules.service_module import register_service, IService

@register_service(name="my_service", meta={"version": "1.0"})
class MyService:
    name: str = "my_service"

    def start(self, config: dict) -> bool:
        # подключиться к ресурсу
        return True

    def stop(self) -> bool:
        # освободить ресурс
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "running"}

# Protocol-совместимость без наследования:
assert isinstance(MyService(), IService)  # True

# --- Auto-discovery (bootstrap в точке входа приложения) ---
from pathlib import Path
from multiprocess_framework.modules.service_module.scanner import discover

result = discover(Path("Services/"), Path("extra/"))
print(result.loaded)   # ['webcam_camera/service.py', 'sql/service.py', ...]
print(result.failed)   # [('broken/service.py', 'ImportError: ...')]
print(result.total)    # 4

# --- Использование реестра ---
from multiprocess_framework.modules.service_module import ServiceRegistry, ServiceLifecycle

registry = ServiceRegistry()   # всегда тот же singleton

for entry in registry.list():
    print(entry.name, entry.lifecycle.value)

# Найти конкретный сервис:
entry = registry.get("my_service")
if entry:
    instance = entry.cls()          # инстанцирование — ответственность вызывающего
    instance.start({"timeout": 5})

# Фильтр по lifecycle:
ready = registry.filter(ServiceLifecycle.READY)
```

## Lifecycle сервиса

Переходы состояний:

```
UNREGISTERED ──> READY ──> RUNNING ──> STOPPED
                   ^           │
                   │           v
                   └────── ERROR
                   ^
                   └── (restart: STOPPED → RUNNING возможен)
```

| Переход | Триггер |
|---------|---------|
| `UNREGISTERED → READY` | `@register_service` при импорте |
| `READY → RUNNING` | application-слой вызывает `instance.start()` |
| `RUNNING → STOPPED` | application-слой вызывает `instance.stop()` |
| `RUNNING → ERROR` | исключение в работе сервиса |
| `ERROR → READY` | ручной reset через `entry.lifecycle = ServiceLifecycle.READY` |
| `STOPPED → RUNNING` | повторный `instance.start()` (рестарт) |

`ServiceRegistry` **не вызывает** `start()/stop()` самостоятельно — только хранит метаданные и класс. Переходы lifecycle выполняет application-слой (например `ServicesPresenter.start_service()`).

## Зависимости

- **Зависит от:** только `stdlib` (`threading`, `dataclasses`, `importlib`, `pathlib`)
- **Используется в:** `multiprocess_prototype/frontend/widgets/tabs/services/` (Task 3.6), `multiprocess_prototype/backend/state/adapters/service_state_adapter.py` (Task 3.5)
- **Слой импортов:** `multiprocess_framework → Services → Plugins → multiprocess_prototype` (обратные запрещены)

## Ограничения

- **Не управляет lifecycle** — реестр не вызывает `start()/stop()` сам; это ответственность application-слоя (например, `ServicesPresenter` в Phase 3).
- **Хранит классы, не экземпляры** — `ServiceEntry.cls` ссылается на класс. Инстанцирование при `start()` выполняет вызывающий. Разные вызывающие могут передавать разные параметры конструктора.
- **Нет hot-reload** — после регистрации класс остаётся в реестре до перезапуска процесса (в отличие от `PluginRegistry`). `clear()` предназначен только для изоляции тестов.
- **Нет интеграции с StateStore / GUI** — синхронизацию состояния обеспечивает `ServiceStateAdapter` в `multiprocess_prototype/` (не часть этого модуля).
- **`isinstance(obj, IService)` проверяет только наличие атрибутов**, но не их сигнатуры — ограничение Python `runtime_checkable`.

## Связанные модули

- [`state_store_module/`](../state_store_module/README.md) — синхронизация статуса сервисов с реактивным деревом через `ServiceStateAdapter` (Task 3.5, application-слой).
- [`process_module/plugins/`](../process_module/README.md) — `PluginManager` использует аналогичный паттерн scanner+registry, но для hot-reload динамических плагинов (другой lifecycle).
- ADR-129 (Task 3.8) — глобальное решение в [`multiprocess_framework/DECISIONS.md`](../../DECISIONS.md): «ServiceRegistry: гибрид с PluginRegistry, lifecycle, scanner».

## Тесты

```bash
# Запускать из корня проекта
pytest multiprocess_framework/modules/service_module/tests/
```

41 тест (26 в `test_registry.py` + 15 в `test_scanner.py`). Покрытие: singleton-гарантия, thread-safety при конкурентной регистрации, дублирующиеся имена → `ValueError`, `clear()` для изоляции между тестами, фильтр по lifecycle, `discover()` с broken-файлом (continue без прерывания), коллизии `module_name` при импорте одноимённых `service.py` из разных поддиректорий.

## Phase 3 trace

Модуль создан в **Phase 3** плана `prototype-skeleton-2026-05` (Tasks 3.1–3.3) на ветке `feat/service-registry`. Полное ТЗ фазы: [`plans/prototype-skeleton-2026-05/phase-3-service-registry.md`](../../../../plans/prototype-skeleton-2026-05/phase-3-service-registry.md). Реальные сервисы-потребители (sql, hikvision_camera, auth, webcam_camera) зарегистрированы в `Services/` через `@register_service` в рамках Task 3.3 (как примеры использования, не как обязательные зависимости модуля).
