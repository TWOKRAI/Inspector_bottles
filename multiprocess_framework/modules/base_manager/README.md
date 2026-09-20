# base_manager

**Базовый модуль фреймворка.** Фундамент для всех менеджеров: жизненный цикл, управление адаптерами и наблюдаемость (логирование, метрики, ошибки).

Два независимых строительных блока:
- **`BaseManager`** — абстрактный менеджер с жизненным циклом и адаптерами.
- **`ObservableMixin`** — наблюдаемость через единый интерфейс к logger/stats/error.

---

## 1. Публичный API

| Класс / Метод | Описание |
|---|---|
| **`BaseManager`** | Абстрактный базовый класс |
| `initialize()` / `shutdown()` | Жизненный цикл (реализуются в подклассе) |
| `attach_adapter(adapter, name)` / `get_adapter(name)` | Управление адаптерами |
| `has_adapter(name)` / `list_adapters()` / `detach_adapter(name)` | Проверка и диагностика |
| `get_stats()` / `get_debug_info()` / `print_debug_info()` | Диагностика |
| **`ObservableMixin`** | Примесь для наблюдаемости |
| `_log_info/debug/warning/error/critical(msg)` | Логирование (приватные методы) |
| `_record_metric(name, value=1)` / `_record_timing(name, value)` | Метрики |
| `_track_error(exc, context)` | Трекирование ошибок |
| `register_manager(name, mgr)` / `unregister_manager(name)` | Регистрация сервисов |
| `enable(name)` / `disable(name)` / `is_enabled(name)` | Управление состоянием |
| `context(name, enabled)` | Контекстный менеджер для временного отключения |
| **`BaseAdapter`** | Базовый класс адаптеров |

---

## 2. Быстрый старт

```python
from base_manager import BaseManager, ObservableMixin, BaseAdapter

# Наследуем BaseManager + ObservableMixin
class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None):
        BaseManager.__init__(self, name)

        # Регистрируем сервисы (менеджеры)
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['stats'] = stats

        ObservableMixin.__init__(
            self,
            managers=managers,
            config={k: True for k in managers},  # включены по умолчанию
        )

    def initialize(self) -> bool:
        self._log_info("RouterManager starting")  # используем логирование
        return True

    def shutdown(self) -> bool:
        return True

    def route(self, message: dict) -> bool:
        self._log_debug(f"Routing message: {message.get('type')}")
        self._record_metric("router.messages_processed")  # метрика
        return True

# Использование
router = RouterManager(
    name="router",
    logger=logger_manager,  # LoggerManager
    stats=stats_manager,    # StatisticsManager
)
router.initialize()
router.route({"type": "test"})
```

---

## 3. Два режима наблюдаемости

### Режим 1 — Приватные методы (по умолчанию, всегда pickle-совместимы)

```python
ObservableMixin.__init__(
    self,
    managers={'logger': logger_mgr, 'stats': stats_mgr}
)

# В методах менеджера:
self._log_info("операция выполнена")
self._log_error("ошибка", exc_info=True)
self._record_metric("operations.count", 1)
self._record_timing("query.duration", 0.042)
self._track_error(exception, context={"method": "process"})
```

**Гарантия:** методы класса, сериализуемы при pickle (Windows spawn). После unpickle возвращают `None` пока не перерегистрированы.

### Режим 2 — Публичные прокси-методы (удобство, опциональный)

```python
ObservableMixin.__init__(
    self,
    managers={'logger': logger_mgr, 'stats': stats_mgr},
    auto_proxy=True,  # создавать публичные методы
)

# Более читаемый стиль:
self.log_info("операция выполнена")
self.record_metric("ops.count", 1)
self.track_error(exc)
```

**Гарантия:** методы создаются динамически, **теряются после unpickle**. Переприменить вручную через `register_manager()`.

---

## 4. Управление адаптерами

Адаптер инкапсулирует интеграцию менеджера с процессом или внешним ресурсом:

```python
class CommandAdapter(BaseAdapter):
    def setup(self) -> bool:
        self._initialized = True
        return True

# Подключить к менеджеру
adapter = CommandAdapter()
manager.attach_adapter(adapter, name="command")

# Получить обратно (явно рекомендуется)
cmd = manager.get_adapter("command")

# Проверить наличие
if manager.has_adapter("command"):
    print(manager.list_adapters())  # ['command']
```

Логирование в адаптере использует fallback:
1. `manager._call_manager('logger', ...)` (если ObservableMixin)
2. Прямой доступ к `process.logger_manager`
3. `print()` как последняя линия защиты

---

## Контракт слота: что можно класть в `logger`/`stats`/`error`

`_call_manager` вызывает менеджер по **каноничному** имени метода: у слота
`logger` это `debug/info/warning/error/critical`, у `stats` —
`record_metric`/`record_timing`, у `error` — `track_error`/`record_error`.
Публичные алиасы самого `ObservableMixin` называются иначе (`log_debug`,
`log_info`, …), поэтому **носитель `ObservableMixin` НЕ является годным
логгером**: `SomeComponent(..., logger=self)` кладёт в слот объект чужого
протокола, и записи компонента теряются. Отдавайте реальный `LoggerManager`
(`self.logger_manager`, доступен после шага 3 `ProcessModule.initialize()`).

Четыре исхода вызова (ADR-BM-005):

| Состояние слота | Поведение |
|---|---|
| слот не зарегистрирован | тихо `None` — законный допуск |
| менеджер `None` | тихо `None` — законный допуск |
| слот выключен (`disable`) | тихо `None` — законный допуск |
| менеджер есть, метода нет | **счётчик + один WARNING** — дефект проводки |
| менеджер есть, метод бросил | **счётчик + один WARNING** — дефект приёмника |

Счётчики читаются снаружи: `manager.manager_call_failures` → `{"logger.warning": 3}`
(и попадают в `get_state()`). WARNING пишется один раз на пару `manager.method`
через stdlib `logging` — `_call_manager` стоит на hot-path каждой записи, и
спам там недопустим; отказать мог сам logger-менеджер, поэтому лог идёт мимо
`_log_*`, иначе была бы рекурсия.

Компоненты, которые зовут `logger._log_*` **напрямую** (а не через свой слот),
с носителем `ObservableMixin` работают штатно: у них indirection через чужой
миксин, и слот резолвится в момент вызова.

### Окно голоса: `should_voice` и `log_windowed` (ADR-LOG-012)

Два публичных метода миксина для повторяющихся состояний. Механизм — в
`logger_module/core/windowed_voice.py` (импорт ленивый, иначе цикл), здесь — разъём.

| Метод | Когда брать |
|---|---|
| `should_voice(key, interval=None)` → `(голосить?, подавлено)` | рядом с голосом есть ФАКТ: счётчик, запись в плоскость ошибок, метрика |
| `log_windowed(key, interval, level, message, **ctx)` → `bool` | голос — это всё, что нужно |

```python
voiced, suppressed = self.should_voice(f"send_error:{reason}")
self._inc_stat("errors")                      # факт — ВСЕГДА, окно его не касается
if voiced:                                    # голос — не чаще окна
    self._log_error(text, suppressed_since_last=suppressed)
```

Разделение обязательств здесь и есть смысл: склеенный вызов «посчитай и напиши» уже стоил
проекту дефекта — в `process_module/health/state.py` запись в плоскость ошибок стоит внутри
ветки «окно позволило», и повтор в окне не оставляет там ни трассы, ни контекста.

Держатель окон — **свой у каждого экземпляра** (ключ `"send_error:no_route"` у двух роутеров
одного процесса — два разных события); общая только политика процесса
(`observability.voices`). Переменную часть сообщения клади в `ctx`, а не в текст: иначе ключ
окна и текст разъезжаются, а дроссель по тексту слепнет.

---

## 5. Управление состоянием

```python
# Отключить временно (для шумных операций)
with manager.context('logger', enabled=False):
    bulk_process()  # не логируется

# Или явно
manager.disable('stats')
manager.initialize()
manager.enable('stats')  # включить после инициализации

# Проверить
if manager.is_enabled('logger'):
    enabled = manager.get_enabled_managers()  # {'logger', 'stats'}
```

---

## 6. Структура файлов (после рефакторинга)

```
base_manager/
├── __init__.py              # публичный API
├── interfaces.py            # Protocol/ABC (IBaseManager, IBaseAdapter, IObservableMixin)
├── core/
│   └── base_manager.py      # BaseManager (жизненный цикл + адаптеры)
├── adapters/
│   └── base_adapter.py      # BaseAdapter (абстрактный класс)
├── mixins/
│   ├── observable_mixin.py  # ObservableMixin (логирование, метрики, ошибки)
│   ├── core/
│   │   └── manager_registry.py  # ManagerRegistry (реестр сервисов)
│   └── proxies/
│       └── proxy_creator.py     # ProxyCreator (генерирует публичные методы)
├── configs/
│   └── base_manager_config.py   # BaseManagerConfig (Pydantic v2 конфиг)
├── utils/
│   └── name_utils.py        # утилиты для имён
├── docs/
│   ├── INTERFACES_USAGE.md  # примеры использования интерфейсов
│   └── OBSERVABLE_ARCHITECTURE.md  # почему два режима, pickle-гарантии
└── tests/
    ├── test_base_manager.py        # lifecycle, adapters, pickle
    ├── test_observable_mixin.py    # приватные методы, proxy-методы, pickle
    └── test_mixin_integration.py   # интеграция с несколькими менеджерами
```

---

## 7. Кто использует модуль

Все менеджеры фреймворка наследуют `BaseManager` и/или `ObservableMixin`:

- `logger_module` (LoggerManager)
- `config_module` (ConfigManager)
- `router_module` (RouterManager)
- `command_module` (CommandManager)
- `worker_module` (WorkerManager)
- `process_module` (ProcessModule)
- `console_module` (ConsoleManager)
- `dispatch_module` (Dispatcher)
- `shared_resources_module` (SharedResourcesManager)
- `error_module` (ErrorManager)
- `statistics_module` (StatisticsManager)
- `sql_module` (SqlManager)
- `frontend_module` (FrontendManager)

---

## 8. Базовый конфиг

`BaseManagerConfig` — опциональный Pydantic v2 конфиг (на границе — dict):

```python
from base_manager import BaseManagerConfig

# Дефолтные настройки (если требуются)
config = BaseManagerConfig()  # если содержимое есть
```

---

## 9. Подробная документация

- [`docs/INTERFACES_USAGE.md`](docs/INTERFACES_USAGE.md) — примеры использования `IBaseManager`, `IBaseAdapter`, `IObservableMixin` для моков и DI.
- [`docs/OBSERVABLE_ARCHITECTURE.md`](docs/OBSERVABLE_ARCHITECTURE.md) — почему два режима наблюдаемости, почему методы класса (не `types.MethodType`), гарантии pickle для Windows spawn.

Архитектурные решения:
- **Локальные:** [`DECISIONS.md`](DECISIONS.md) (ADR-114…117 — удаления плагинов, декораторов, __getattr__, on_event/emit_event).
- **Глобальные:** [`multiprocess_framework/DECISIONS.md`](../../../DECISIONS.md) (ADR-008 Dict at Boundary, правила фреймворка).

---

## 10. Запуск тестов

```bash
# Из репозитория
PYTHONPATH="$PWD" pytest multiprocess_framework/modules/base_manager/tests -v

# Или через валидацию фреймворка
python scripts/validate.py
```

**Статус:** Модуль завершён. Все 52 теста проходят (4 файла, после удаления 10 plugin/events-тестов). Публичный API не изменился. LOC сокращены на 39% (с 2425 до 1474).
