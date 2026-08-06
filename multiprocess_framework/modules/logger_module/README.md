# logger_module

Менеджер логирования, интегрированный в единую иерархию через `ChannelRoutingManager`.
Собирает логи от всех менеджеров через `ObservableMixin`, принимает `LOG`-сообщения от дочерних
процессов через `RouterManager` и записывает в множество каналов **синхронно**
(батчинг снят в Ф7.4: замер показал ноль экономии на границе ОС и худший хвост).

> **Observability control plane:** новый тип sink добавляется одной строкой
> `register_sink_factory(type, cls)` (`channels/log_channel.py`) — без правки `create_channel`.
> Runtime-перенастройка каналов/уровней — `reconfigure(config: dict)` (база CRM, хук
> `_rebuild_from_config` + `invalidate_decision_cache`). Hot-reload из файла —
> `process_module/managers/observability_reload.py`. Точки расширения и якоря —
> ADR-CRM-006 в [`../channel_routing_module/DECISIONS.md`](../channel_routing_module/DECISIONS.md).

---

## Архитектура и наследование

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ← базовый класс для менеджеров с каналами
        │
        ▼
LoggerManager (синхронная запись, scope-based routing, ILogChannel)
        │
        ▼
ErrorManager  (override log() для level-based routing)
```

**Что дал LoggerManager от ChannelRoutingManager:**
- `_channel_registry` (thread-safe RLock вместо `channels: Dict`)
- `_dispatcher` для маршрутизации по ключу (scope, level)
- `_normalize_config()` — обработка Dict | RegisterBase | None
- Единая иерархия `ILogChannel(IChannel)`

**Что осталось специфичным LoggerManager:**
- Scope-based routing (SYSTEM, BUSINESS, PERFORMANCE, AUDIT, SECURITY, DEBUG)
- Логирование с контекстом (`push_context` / `pop_context`)
- Module-specific логирование (`enable_module_logging`)
- Priority flush для ERROR/CRITICAL

---

## Роль в архитектуре

```
┌──────────────────────────────────────────────────────────────────────┐
│  Любой менеджер (BaseManager + ObservableMixin)                      │
│                                                                        │
│  ObservableMixin.__init__(managers={'logger': logger_manager})        │
│  self._log_info("message")   ──→  LoggerManager.info(msg)            │
│  self._log_error("error")    ──→  LoggerManager.error(msg)           │
└──────────────────────────────────────────────────────────────────────┘
                    │
        ┌───────────▼──────────────────────────────────┐
        │         LoggerManager                         │
        │    (наследует ChannelRoutingManager)          │
        │                                               │
        │  ┌────────────┐  ┌──────────────┐  ┌──────┐  │
        │  │ ScopeFilter│  │ Процессоры   │  │Router│  │
        │  │ (кэш scope)│  │  (процессоры)│  │route │  │
        │  └─────┬──────┘  └───┬──────────┘  └───┬──┘  │
        └────────┼──────────────┼─────────────────┼────┘
                 │              │                 │
        ┌────────▼──────────────▼─────────────────▼────┐
        │  ChannelRoutingManager._dispatcher           │
        │         (scope/level routing)                │
        │  ┌─────────────────────────────────────────┐ │
        │  │  scope dispatcher (from CRM)            │ │
        │  │  data → scope filter → channel list     │ │
        │  └─────────────────────────────────────────┘ │
        └─────────────────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │     ILogChannel (от CRM через наследование)│
        │  FileChannel  ConsoleChannel  HttpChannel  │
        │  + кастомные каналы (DatabaseChannel...) │
        └───────────────────────────────────────────┘
```

**Интеграция через ObservableMixin:**

| Метод ObservableMixin | Маршрутизируется в | Scope |
|---|---|---|
| `self._log_debug(msg)` | `LoggerManager.debug(msg)` | DEBUG |
| `self._log_info(msg)` | `LoggerManager.info(msg)` | BUSINESS |
| `self._log_warning(msg)` | `LoggerManager.warning(msg)` | SYSTEM |
| `self._log_error(msg)` | `LoggerManager.error(msg)` | SYSTEM |
| `self._log_critical(msg)` | `LoggerManager.critical(msg)` | SYSTEM |

---

## Структура модуля

```
logger_module/
├── interfaces.py             ← Публичный контракт (ILoggerManager, ILogChannel)
├── __init__.py               ← Публичный API
│
├── core/
│   ├── logger_manager.py     ← LoggerManager(ChannelRoutingManager, ILoggerManager)
│   ├── log_types.py          ← LogRecord (dataclass)
│   ├── log_config.py         ← реэкспорт LoggerManagerConfig, LogLevel, LogScope
│   └── log_enums.py          ← LogLevel (enum), LogScope (строковые константы, Ф2.4)
├── configs/
│   └── logger_manager_config.py  ← LoggerManagerConfig(ChannelRoutingConfig)
│
├── channels/
│   └── log_channel.py        ← LogChannel(ILogChannel), File/Console/Http/FrameTrace/Memory/Null
│
├── adapters/
│   └── std_facade.py         ← StdLoggerFacade / get_std_logger (единственный вид)
│
└── tests/
    └── test_logger_manager.py
```

---

## Быстрый старт

```python
from logger_module import LoggerManager, LoggerManagerConfig, LogLevel, LogScope

# Вариант 1: минимальная конфигурация
logger = LoggerManager(manager_name="app_logger")
logger.initialize()

# Вариант 2: через dict (Dict at Boundary)
logger = LoggerManager(
    manager_name="app_logger",
    config={
        "app_name": "inspector",
        "default_level": "INFO",
        "channels": {
            "console": {"type": "console", "enabled": True},
            "file":    {"type": "file", "enabled": True, "file_path": "logs/app.log"},
        },
    }
)
logger.initialize()

# Вариант 3: через LoggerManagerConfig (SchemaBase)
config = LoggerManagerConfig.model_validate({
    "app_name": "inspector",
    "default_level": "INFO",
    "channels": {...},
})
logger = LoggerManager(manager_name="app_logger", config=config)
logger.initialize()
```

---

## API: LoggerManager

### Жизненный цикл

| Метод | Описание |
|---|---|
| `initialize()` | Инициализировать каналы, dispatcher, buffer из CRM. Запустить батчер. |
| `shutdown()` | `flush()` → закрыть каналы → остановить buffer → остановить dispatcher. |

### Быстрые методы по уровню

```python
logger.debug("variable value", module="router_module")
logger.info("process started", module="orchestrator")
logger.warning("queue almost full", module="worker_module")
logger.error("connection failed", module="network")
logger.critical("out of memory", module="allocator")
```

### Прикладной код в stdlib-стиле — `get_std_logger()`

Модуль, написанный как `logger = logging.getLogger(__name__)`, в процессе фреймворка
пишет в никуда: у корневого stdlib-логгера нет хендлеров, запись не попадает ни в
`logs/<proc>/*.log`, ни в консольный канал. Мост — `StdLoggerFacade`:

```python
from multiprocess_framework.modules.logger_module import get_std_logger

logger = get_std_logger("gui")          # имя per-module файла: gui/trace/camera/…
logger.warning("процесс '%s' не удалён", name)   # → logs/<proc>/gui.log + scope-каналы
```

Поверхность совпадает со stdlib (`debug/info/warning/error/critical/exception/log`),
включая `%`-форматирование. Если `LoggerManager` ещё не поднят — запись уходит в
обычный `logging` (фолбэк `mpf.<module>`), а не теряется. Резолв менеджера ленивый:
модули импортируются до `init_logging()`.

#### Конвенция имени — `__name__`, а не корзина (Ф6.0, решение Р-А)

**Единственная форма в прикладном и фреймворковом коде:**

```python
from multiprocess_framework.modules.logger_module import get_std_logger

logger = get_std_logger(__name__)
```

Ручные корзины — `get_std_logger("gui")`, `"camera"`, `"renderer"` — в мигрируемом
коде **запрещены**. Причина не стилистическая:

- **Адресуемость.** Девять корзин дают девять ручек на сотню файлов. `__name__` даёт
  ручку на каждый файл и на любой пакет выше него — управляемость начинается с того,
  что объект можно назвать.
- **Одна миграция вместо двух.** Иерархический резолвер (2.2, longest-prefix) ест
  ровно это имя. Корзины пришлось бы мигрировать второй раз — и попутно они
  зацементировали бы прикладные имена (`gui`, `camera`) внутри кода фреймворка.
- **Смешанное пространство имён ломает longest-prefix.** Если часть файлов зовётся
  `multiprocess_prototype.frontend.widgets…`, а часть — `gui`, префиксное правило
  становится частично бессмысленным: у второй половины нет префикса, к которому его
  прикладывать.

**Что теряется сейчас и почему это не регресс.** `__name__` не совпадает с именем
per-module файла, поэтому запись не попадёт в `logs/<proc>/gui.log` — только в
scope-каналы (`console`, `system.log`). Для мигрируемых файлов потеря мнимая: до
миграции они не писали **никуда** (у stdlib-root в процессах фреймворка нет
хендлеров). Раскладка по файлам вернётся правилом-префиксом в конфиге при 2.2.

**Имя переменной кодмод не трогает.** Канон для нового кода — `logger`, но 12 из 107
мигрируемых файлов держат `_logger`; переименование потянуло бы за собой все точки
использования и раздуло бы диф ради стиля. Кодмод переписывает только правую часть.

**Именованные исключения** (корзина вместо `__name__` оставлена сознательно):

| Где | Аргумент | Почему |
|-----|----------|--------|
| `process_manager_module/runner/process_runner.py:120` | имя процесса | Вид принадлежит процессу целиком, а не модулю; `__name__` здесь назвал бы раннер, а не то, что пишет |
| `process_manager_module/launcher/spawner.py:73` | `"spawner"` | То же: запись идёт от лица подсистемы запуска, до и вне модульного дерева дочернего процесса |
| `modules/_fallback.py:95` | имя вызывающего + `fallback_name` | Аварийный выход: фолбэку нужен stdlib-логгер с **точным** именем модуля, а не с префиксом `mpf.` |
| `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py:37` | `"gui"` | Уже живой: пишет в `gui.log` сегодня. Перевод на `__name__` — **настоящий** регресс (в отличие от мигрируемых), поэтому откладывается до правила-префикса 2.2 |
| `multiprocess_prototype/frontend/bridge/topology_bridge.py:42` | `"trace"` | То же |

### Методы по области (scope явный)

```python
logger.system(LogLevel.INFO, "LoggerManager initialized", module="logger_module")
logger.business(LogLevel.INFO, "frame processed", module="processor")
logger.performance(LogLevel.DEBUG, "fps=60", module="camera")
logger.audit(LogLevel.INFO, "config changed", module="config_module")
logger.security(LogLevel.WARNING, "unauthorized access attempt", module="api")
```

### Полный метод `log()` — все параметры

```python
logger.log(
    scope=LogScope.SYSTEM,
    level=LogLevel.ERROR,
    message="critical component failed",
    module="router_module",
    trace_id="abc-123",      # **extra поля
    retry_count=3,
)
```

### Своя группа логов (Ф2.4) — без единой правки фреймворка

`scope` — обычная **строка**, а `LogScope` лишь набор преднастроенных констант.
Новая группа заводится конфигом приложения и сразу получает свой порог и свои
приёмники:

```yaml
# system.yaml приложения
observability:
  scopes:
    КОНВЕЙЕР: { enabled: true, min_level: WARNING, channels: [цех_file] }
```

```python
logger.log("КОНВЕЙЕР", LogLevel.ERROR, "деталь не прошла контроль", "мод")
```

Ключ конфига, константа и значение `scope` в записи — **одна строка**; регистр
приводится к заглавным на границе конфига, поэтому `конвейер:` в YAML попадёт в
ту же группу, а не заведёт вторую, недостижимую.

Группа, в которую пишут, но которой в конфиге нет, — законное состояние (ещё не
объявили), но **не молчаливое**: логгер один раз на имя говорит вслух через
аварийный выход и называет фактический маршрут, а список таких имён отдаёт
`unknown_scopes()` и readback `introspect.observability` →
`effective.logger.unknown_scopes`.

### Контекстное логирование

```python
# Все последующие вызовы автоматически получат эти поля
logger.push_context(request_id="req-42", user="admin")
logger.info("processing request")   # → extra = {request_id: req-42, user: admin}
logger.warning("slow query")
logger.pop_context()

# Факт про ПРОЦЕСС ЦЕЛИКОМ — виден из всех потоков
logger.set_base_context(proc_name="camera_0")
logger.clear_base_context()

# Контекст как контекстный менеджер (через contextvars)
from logger_module.core.logger_manager import log_context
token = log_context.set({"trace_id": "xyz-789"})
logger.info("message")  # → extra = {trace_id: xyz-789}
log_context.reset(token)
```

**Два слоя, и это не украшение API (Ф0.5).** `push_context` действительно
потоковый — контекст виден только своему потоку (и своему asyncio-таску), соседний
поток его не видит и своего не теряет. До Ф0.5 стек был **один на инстанс** вопреки
имени `_get_thread_context()`: два потока перетирали контекст друг другу, и запись
могла уехать с чужим `request_id`.

Но одного потокового слоя мало. Единственный производственный потребитель — процесс,
который на старте кладёт `proc_name` **из главного потока**, а пишут логи потоки-воркеры.
Сделай контекст просто thread-local — и `proc_name` молча исчезнет из всех записей
воркеров (это верно и для `ContextVar`: новый поток стартует с чистым контекстом).
Поэтому слоёв два, по числу фактов:

| Слой | Что кладут | Кто видит |
|---|---|---|
| `log_context` (ContextVar) | публичная «форточка» | текущий поток/таск |
| `set_base_context()` | факт про процесс (`proc_name`) | **все потоки** |
| `push_context()` | факт про текущую работу (`request_id`) | только свой поток/таск |
| `extra=` в вызове | факт про конкретную запись | только эта запись |

Приоритет — сверху вниз по таблице: каждый следующий слой знает больше про конкретную
запись и перекрывает предыдущий по совпадающим ключам.

> ⚠️ **Контекст привязан к потоку, а не к задаче.** Пул потоков переиспользует поток,
> поэтому `push_context` без парного `pop_context` достанется следующей задаче на том же
> потоке. Снимает тот, кто положил — по `finally`. Свойство зафиксировано тестом
> `test_unpopped_context_persists_on_a_reused_thread`.

### Отдельные файлы для модулей

```python
# Включить отдельный файл логирования для модуля
logger.enable_module_logging("router_module", "logs/router.log")
logger.info("routing started", module="router_module")  # → записывается и в router.log

# Выключить
logger.disable_module_logging("router_module")
```

> ⚠️ Совпадение **точное**: запись попадёт в `router.log`, только если `module` равен
> `"router_module"` буква в букву. После Ф6 адрес записи — это `__name__`
> (`multiprocess_framework.modules.router_module.core.router_manager`), и точное
> совпадение с ним не случается. Живой прогон 2026-08-03: из 384 созданных
> per-module файлов непустыми оказались 4, и все четыре — по совпадению имени
> процесса с ключом файла. Адресная раскладка по файлам делается правилами
> иерархии (ниже), а не этим механизмом; сам он свернётся в правило в задаче 2.6.

---

## Правила по имени источника — иерархия и longest-prefix (Ф2.2)

Вторая ось адресации рядом со скоупами. **Скоуп — оптовая ручка** («весь `BUSINESS`
тише»), **правило имени — адресная**: любой префикс пакета или отдельный файл.

```yaml
observability:
  loggers:
    "":                                              # корень — пустая строка
      level: WARNING
    multiprocess_framework.modules.router_module:    # весь пакет роутера
      level: DEBUG
      channels: [router_file]
    Plugins.vision.capture.hikvision:                # один файл
      level: INFO
```

**Действует самое длинное совпавшее правило.** Новый плагин
`Plugins.vision.capture.basler` автоматически подчиняется правилу
`Plugins.vision.capture` — конфиг при добавлении плагина не трогают.

```
Plugins.vision.capture.basler → Plugins.vision.capture → Plugins.vision → Plugins → ""
```

Что нужно знать, чтобы не наступить:

| Правило | Смысл |
|---|---|
| **Имя сильнее скоупа** | Порог задаёт правило; скоуп остаётся поставщиком набора приёмников по умолчанию. Это единственный расклад, при котором «DEBUG одному файлу» не требует открыть шлюз всему скоупу |
| **И сильнее `enabled` скоупа** | Скоуп `DEBUG` в дефолтах выключен; правило имени его разбудит для своего поддерева. Цена: опечатка в префиксе разбудит выключенный скоуп — принято сознательно |
| **Две оси независимы** | Правило может задать `level` и промолчать про `channels` — приёмники придут с более короткого префикса, и наоборот |
| **Ключа нет ≠ `channels: []`** | Отсутствие ключа — «наследую»; пустой список — «приёмников нет, и это решение» (запись считается потерей класса `records_without_channels`, а не уходит в скоуп) |
| **Совпадение по границе точки** | Правило `vision.capture` не подхватит `vision.captureX` |
| **Пустая таблица — дефолт** | Без правил гейт и маршрут работают ровно как до Ф2.2 |
| **Ошибку правилом не заглушить** | Severity-путь `ErrorManager` (WARNING+) правила не спрашивает вовсе — инвариант «ошибка не теряется» |

Резолв доступен и снаружи — для пульта и readback:

```python
logger.effective_level("Plugins.vision.capture.basler")     # "INFO" | None — правило молчит
logger.effective_channels("Plugins.vision.capture.basler")  # ("named_file",) | () | None
```

Обе функции отвечают **про одну ось решения**, а не про судьбу записи: приёмник может
быть снят оператором, а плоскость ошибок ходит своим путём.

---

## Запись синхронна (батчинг снят в Ф7.4)

Каждая запись доезжает до канала в потоке-эмитенте: после возврата из `logger.info()`
она уже на диске. Отложенного пути нет ни на одном уровне.

**Почему батчинг снят.** Замер (20 000 записей в файловый канал):

| | p50 | p95 | p99 | mean | write() | flush() |
|---|---|---|---|---|---|---|
| батч | 3.6 мкс | 4.9 | **1347.5** | 20.8 | 20 001 | 40 002 |
| синхронно | 20.9 мкс | 28.4 | **75.2** | 23.4 | 20 000 | 40 000 |

Вызовов на границе ОС батчинг не экономил вовсе (handler пишет и сбрасывает на каждую
запись), с потока-эмитента работу не уносил (mean почти равен — пачку сбрасывает тот же
поток, который её переполнил), а хвост портил в 18 раз. Живая пара на стенде g1
(90 с, DEBUG, по два прогона): FPS и объём логов в пределах шума, хвост цикла лучше без
батчинга. Половина сложности CRM-буфера (`_in_flight`, барьеры, контракт `flush_fn → int`)
существовала ради него — снята вместе с ним.

**Что исчезло вместе с буфером.** Он был единственным поглотителем залипшего стока:
теперь медленный приёмник блокирует поток-эмитент (у консоли есть свой дедлайн записи,
у файлового стока — локальный диск). Политика на этот случай — предмет Ф7.2.

**Снятые ключи конфига** (`enable_batching`, `batch_size`, `batch_interval`,
`batch_max_pending`, `batch_overflow_policy`) больше ничего не делают. Схема принимает
лишние ключи молча, поэтому секция `observability` **жалуется вслух**, если встретит их
в конфиге, — иначе оператор правил бы ручку без единого следствия.

```python
# Принудительный сброс (например, при shutdown)
logger.flush()
```

**Медленный сток.** Раньше пачка канала копила записи с потолком `batch_max_pending` и
называла потерю (`dropped`, `dropped_by_channel`). Буфера нет — нет и этого поглотителя:
залипший приёмник блокирует поток-эмитент. Консоль защищена собственным дедлайном записи,
файловый сток локален; общая политика (async → sync → drop → flush) — предмет Ф7.2.

**Пол ошибок.** Если запись `ERROR`/`CRITICAL` не принял **ни один** канал (приёмники выключены
в конфиге, сняты через `logger.sink.disable` или все `write` упали), она уходит в
`errors_floor.jsonl` рядом с логами — JSON Lines, полная запись с трейсбеком и `extra`.
Пол пишет **только** при нуле принявших каналов, поэтому второй копии записи не создаёт.
Непустой `errors_floor.jsonl` — сигнал «штатный маршрут ошибок сломан», а не норма.
Счётчики: `get_stats()["errors_to_floor"]` и секция `error_floor` (`path` / `written` /
`failures`); у живого процесса — `introspect.observability`.

**Канала нет — запись не исчезает бесследно (Ф0.4).** Имя канала может не резолвиться: опечатка
в `scopes`, канал снят через `logger.sink.disable`, module-канал удалён. Раньше такая запись
пропадала молча на обоих путях доставки. Теперь она считается **по записи**, а имя виновника
названо:

| Ключ `get_stats()` | Что значит |
|---|---|
| `unresolved_channel_records` | сколько записей адресовано несуществующему каналу |
| `unresolved_channels` | то же в разбивке `{имя канала: число}` |
| `channel_write_errors` | сколько записей потеряно из-за **исключения** в `write()` канала |
| `channel_write_errors_by_channel` | то же в разбивке по каналам |

Отказ канала статусом (`{"status": "error"}`) в `channel_write_errors` **не** попадает — он виден
как разница «отдано минус принято» (`channel_refused_records`). Все четыре ключа присутствуют
всегда, нулями: «ключа нет» и «потерь нет» — разные факты. Наружу выходят через
`introspect.observability`.

Предупреждение об этом пишется в fallback-логгер (stdlib) **ровно один раз на имя канала** за
жизнь процесса — имя от записи к записи не меняется, а лог-шторм внутри логгера ровно та
болезнь, ради которой соседние `except` стоят молча. Учёт при этом не глушится никогда.
Для `ERROR`/`CRITICAL` «канала нет» не означает потерю: запись подхватывает пол (см. выше),
поэтому `unresolved_channel_records` и `errors_to_floor` растут вместе и не противоречат.

**Sink-control и tap'ы живут в базе (Ф0.6).** `set_sink_enabled`, `add_tap` / `remove_tap`
и `_fallback_log` подняты в `ChannelRoutingManager` — они одинаковы у логов, ошибок и
статистики, и держать три копии было бы третьей копией одной операции. У логгера остался
только хук `_recreate_channel`: «откуда взять параметры канала при включении обратно»
(из `config.channels[name]`, даже если там `enabled=False` — включение через control-plane
это явный override оператора).

Методы переименованы: `add_log_tap` / `remove_log_tap` → **`add_tap` / `remove_tap`**.
Старые имена удалены, а не оставлены обёртками. Команда `logger.sink.enable|disable`
принимает `manager=logger|error|stats` (дефолт `logger` — старые вызовы бьют туда же).

**Thread-safety:** запись синхронна, общего изменяемого состояния между потоками на пути
записи нет; несколько потоков одного процесса могут одновременно вызывать `logger.info()`. Счётчики потерь Ф0.4 защищены
отдельным локом, который берётся **только** на пути потери (замер: 12 потоков × 3000 записей без
лока дают 29 261 инкремент из 36 000 — счётчик потерь врал бы в меньшую сторону).

---

## Каналы (ILogChannel)

Все каналы наследуют `ILogChannel(IChannel)` из `channel_routing_module`:

```python
class ILogChannel(IChannel):
    @property
    def name(self) -> str: ...
    @property
    def channel_type(self) -> str: return "log"
    def write(self, data: Dict[str, Any]) -> Dict[str, Any]: ...
    def close(self) -> None: ...
    def get_info(self) -> Dict[str, Any]: ...
```

### Встроенные каналы

| `type` в конфиге | Класс | Куда попадает запись |
|---|---|---|
| `file` | `FileChannel` | файл с ротацией |
| `console` | `ConsoleChannel` | терминал |
| `http` | `HttpChannel` | удалённый сервис логирования |
| `frame_trace` | `FrameTraceChannel` | снимок одного кадра, файл перезаписывается |
| `memory` | `MemoryChannel` | кольцо в памяти процесса, читается по запросу |
| `null` | `NullChannel` | никуда — намеренно |

**`memory` — единственное место, где последние N записей достаются
РЕТРОСПЕКТИВНО.** Живой хвост (`log.tail.subscribe`) — подписка: кто не
подписался заранее, прошлое не увидит; `ObservabilityHub` — транзитное кольцо,
его дренирует владелец; `ObservabilityStore` — уже диск. Ёмкость (`capacity`,
дефолт 500) считает **записи, а не байты**, и это единственная граница: запись
держит свой `extra`, поэтому большое кольцо способно удерживать в живых чужие
объекты. Читается командой `logger.sink.tail` (`sink`, `limit`, `manager`).
Вытеснение старого — контракт кольца, а не потеря: `evicted` живёт в
`get_info` и в `LOSS_COUNTER_KEYS` не входит.

**`null` — доставка, а не потеря.** Оператор выбрал этот приёмник явно, и
раздувать ему класс потерь значило бы обесценить счётчик. Обратная сторона
названа вслух: скоуп (или severity-маршрут) уровня ERROR, ведущий ТОЛЬКО в
`null`, глушит пол ошибок — запись «доставлена», floor молчит, счётчики чисты.
Это законно, но конфигурация выдаёт WARNING при поднятии каналов
(`LoggerCore._warn_on_silenced_error_scopes`, у плоскости ошибок —
`ErrorManager._warn_on_silenced_severity_routes`).

### Кастомный канал

```python
from logger_module.interfaces import ILogChannel

class DatabaseChannel(ILogChannel):
    @property
    def name(self) -> str:
        return "database"

    def write(self, record: dict) -> dict:
        try:
            db.insert("logs", record)
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self) -> None:
        db.close()

    def get_info(self) -> dict:
        return {"name": self.name, "active": db.is_connected()}

# Регистрация через register_channel()
logger.register_channel(DatabaseChannel())
```

---

## Конфигурация каналов

```python
from logger_module import LoggerManagerConfig

config = LoggerManagerConfig.model_validate({
    "app_name": "my_app",
    "default_level": "INFO",

    "channels": {
        "console": {
            "type": "console",
            "enabled": True,
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "app_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/app.log",
            "max_size": 10485760,   # 10 MB
            "backup_count": 5,
        },
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/errors.log",
        },
    },

    "scopes": {
        "SYSTEM":      {"enabled": True,  "min_level": "WARNING", "channels": ["console", "app_file"]},
        "BUSINESS":    {"enabled": True,  "min_level": "INFO",    "channels": ["app_file"]},
        "DEBUG":       {"enabled": False, "min_level": "DEBUG"},
        "PERFORMANCE": {"enabled": True,  "min_level": "INFO",    "channels": ["app_file"]},
    },

    "modules": {
        "router_module": {"enabled": True, "file_path": "logs/router.log", "min_level": "DEBUG"},
    },
})
```

---

## Ретеншен каталога логов (Ф0.7)

Ротация ограничивает **каждый файл** (`max_size` × `backup_count`), но не ограничивает
**число файлов**. Живой замер 2026-07-26: `logs/` = **730 файлов / 291 МБ**, старейший от
2026-05-05 (82 дня, ни одного удаления), ~700 различных `.log`-баз. При исправно
работающей ротации теоретический потолок — **41 ГБ**: потолок стоял не там, где рост.

Три настройки закрывают именно рост. **Обе политики выключены по умолчанию** — механизм,
который сам решает что удалить, не включается молча.

| Поле | По умолчанию | Что делает |
|---|---|---|
| `retention_days` | `0` (выкл) | Удалять файлы старше N суток по `mtime` |
| `retention_total_mb` | `0` (выкл) | Потолок суммарного веса каталога; при превышении удаляются **старейшие**, пока не уйдёт под потолок |
| `compress_rotated` | `False` | Сжимать ротированные бэкапы: `foo.log.1` → `foo.log.1.gz` |

Задаются и напрямую в `LoggerManagerConfig`, и через секцию `observability` — то есть
применяются **hot-reload'ом**, без перезапуска процесса.

**Что нужно знать до включения:**

- **Метётся свой подкаталог, рекурсивно.** У процесса это `logs/<имя процесса>/` (вместе с
  `trace/`), поэтому в штатной раскладке пересечения с чужими активными файлами нет.
  **Но это не структурная гарантия** (уточнено ревью фазы, воспроизведено): защита — это
  список своих открытых файлов плюс блокировка ФС. Менеджер, нацеленный на чужой каталог,
  активный файл соседа удалить ПЫТАЕТСЯ; на Windows тот выживает по `WinError 32`, на POSIX
  был бы удалён. Обратная сторона: каталоги умерших процессов не метёт никто — разовая
  уборка, а не рост.
- **Ретеншен получает только `logger`.** `expand_observability` не отдаёт эти поля
  `error`: каталог логов один, и второй подметальщик означал бы два прохода по одному
  дереву с гонкой за одни и те же файлы.
- **Активные файлы и `errors_floor.jsonl` не трогаются никогда.** Первые — потому что
  удалить файл под работающим хэндлером значит молча потерять поток записей; второй —
  потому что это последнее свидетельство о падении (Ф0.9), и политика дискового места не
  отменяет политику сохранности улик.
- **Порядок шагов:** возраст → компрессия → потолок. Потолок считает вес уже **после**
  сжатия, иначе компрессия ничего не давала бы.
- **Возраст переносится на архив** (`os.utime`): иначе сжатый бэкап выглядел бы
  свежесозданным и по возрасту не удалялся бы никогда — две политики работали бы друг
  против друга.
- **`.gz` иммунитета не имеет** — для возраста и потолка это обычный файл.

**Что видно снаружи** (`get_stats()`, `introspect.observability` → `counters`):
`retention_files_deleted`, `retention_files_compressed`, `retention_delete_failures`,
`retention_compress_failures`, `retention_bytes_freed`. Ключи присутствуют всегда, в том
числе нулями: «ключа нет» и «чистка не работала» — разные факты. Ненулевой
`retention_delete_failures` при нулевом `retention_files_deleted` означает «ретеншен
настроен, но удалить не может» (на Windows — файл занят другим процессом); предупреждение
об этом звучит **один раз на файл**, счётчик при этом растёт всегда.

```python
config = LoggerManagerConfig.model_validate({
    "log_directory": "logs",
    "retention_days": 14,        # хранить две недели
    "retention_total_mb": 2048,  # и не больше 2 ГБ на каталог
    "compress_rotated": True,
})
```

---

## Предел ожидания консоли (R2)

Консольный канал пишет **синхронно в потоке-эмитенте**, а после Ф0.9 путь
`error`/`critical` идёт мимо батч-буфера вообще — прямо в `stream.write()` вызывающего
потока. Если stdout перенаправлен в трубу, которую никто не читает, поток виснет навсегда;
до этой правки за ним выстраивались **все** остальные потоки-эмитенты, и один заткнувшийся
приёмник останавливал процесс целиком.

Предел ставится там, где он достижим: ожидание освобождения канала ограничено
`ConsoleChannel._BUSY_WAIT_SEC` (0.25 с), после чего запись отбрасывается со статусом
`error`. Именно `error`, а не `skipped`: запись никуда не попала, и **пол ошибок (Ф0.9)
обязан это узнать** — иначе предел чинил бы одну потерю, создавая другую.

Обычная конкуренция стоит микросекунды и в предел не упирается: потери начинаются только на
реально застрявшей консоли. Файловые каналы затык консоли не затрагивает.

**Чего это НЕ делает, и это надо знать честно:** поток, который **уже вошёл** в блокирующий
`stream.write()`, остаётся заблокированным. Ограничить его можно только вынеся запись в
отдельный поток-писатель — а это размен «консоль переживает падение» на «консоль
ограничена», решение про диагностический канал, которое принимает владелец. Захват сокращён
с «весь процесс» до «один поток», и он теперь считается.

**Что видно снаружи** (`get_stats()`, `introspect.observability` → `counters`):
`sink_writes_dropped` и `sink_slow_writes` — имена нейтральны по стоку с Ф7.2, потому что
лесенка переехала в базу канала и в сумму входят теперь и файловые потери (прежние
`console_*` врали бы по имени). Менеджер отдаёт **сумму «унесённое ушедшими каналами» +
«живое»**, а не собственную копию и не только живое: канал уходит из реестра вместе со
своей историей, а `logger.sink.disable`/`reconfigure` делают ровно во время инцидента.

Рядом (Ф7.х) — то, чего сумма не говорит: `sink_degraded` (`bool`) и
`sink_degraded_channels` (имена) отвечают «этот сток теряет **сейчас**», а
`sink_writes_dropped_by_channel` — «**чьи** потери». Порог «медленно» — 0.05 с,
`get_info()` канала дополнительно отдаёт `max_write_sec`. Предупреждение о занятом стоке
троттлится (не чаще раза в 60 с), счётчик при этом растёт всегда.

**Единица защиты — сток, а не канал** (Ф7.х). Лесенка берёт лок *хэндлера*: каналы, делящие
один файл через общий rotating-хэндлер (`messages_file` + `router_messages` → `messages.log`),
делят и предел ожидания, и сериализацию записи. Пер-канальный лок давал обратное — второй
канал входил в тот же `stream.write` без предела вообще.

---

## Прием LOG-сообщений от дочерних процессов

Логи от дочерних процессов приходят через RouterManager как `Message(type='log')`.

```python
# При настройке оркестратора:
router.register_message_handler(
    key="log",
    handler=lambda msg: logger.log(
        scope=msg.get("metadata", {}).get("scope", LogScope.BUSINESS).upper(),
        level=LogLevel[msg.get("level", "INFO").upper()],
        message=msg.get("message", ""),
        module=msg.get("module", "unknown"),
    ),
)
```

---

## Интеграция через ObservableMixin

Любой менеджер, использующий `ObservableMixin`, автоматически получает доступ к логированию:

```python
from base_manager import BaseManager, ObservableMixin

class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, **kwargs):
        BaseManager.__init__(self, name)
        managers = {'logger': logger} if logger else {}

        ObservableMixin.__init__(
            self,
            managers=managers,
            config={'logger': True},
            auto_proxy=True,
        )

    def send(self, msg):
        self._log_debug(f"sending {msg.get('type')}")  # → LoggerManager.debug()
        # ...
        self._log_info("sent successfully")             # → LoggerManager.info()
```

---

## Dict at Boundary

| Формат | Пример |
|---|---|
| `None` | `LoggerManager()` — дефолтный конфиг |
| `dict` | `{"app_name": "app", "default_level": "INFO", "channels": {...}}` |
| `LoggerManagerConfig` | `LoggerManager(config=...)` |
| Объект с `build()` | `build()` возвращает `(manager_name: str, config: dict)` |

---

## Тесты

```bash
cd multiprocess_framework/refactored
pytest modules/logger_module/tests/ -v
```

Покрытие (~30 тестов):
- Жизненный цикл: `initialize()` / `shutdown()`
- Логирование по уровням: debug/info/warning/error/critical
- Логирование по областям: system/business/performance/audit/security
- Батчинг: size-based, time-based (ошибки идут мимо батчинга — см. «Батчинг» выше)
- Пол ошибок: синхронная запись, floor при нуле приёмников, отсутствие дубля
- Контекст: push/pop, contextvars integration
- Каналы: регистрация, удаление, кастомные каналы
- Интеграция с RouterManager: приём LOG-сообщений
