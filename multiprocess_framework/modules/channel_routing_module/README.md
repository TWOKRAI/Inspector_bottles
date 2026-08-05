# channel_routing_module — Базовый модуль маршрутизации

> «Телефонная станция для данных: принимает сигнал, смотрит в справочник, отправляет в нужный канал.»

Устраняет дублирование, существовавшее между `RouterManager`, `LoggerManager` и `ErrorManager`.
Один раз написанный `ChannelRoutingManager` становится базовым классом для всех.

---

## Проблема, которую решает модуль

До создания этого модуля три менеджера независимо реализовывали один паттерн:

```
RouterManager          LoggerManager          ErrorManager
─────────────────      ────────────────       ─────────────────
ChannelRegistry        channels: Dict         (через LoggerManager)
  (threading.RLock)      (без lock ⚠️)
AsyncSender            BatchManager           (через LoggerManager)
  (PriorityQueue)        (deque + timer)
Dispatcher             LogDispatcher          LogDispatcher
  (channel routing)      (обёртка над          (level routing)
                          Dispatcher)
register_channel()     (свой метод)           (через LoggerManager)
unregister_channel()   (свой метод)           (через LoggerManager)
get_channel()          (отсутствует ⚠️)       (отсутствует ⚠️)
```

**Результат**: 3 независимых реализации → ошибки в одном не исправляются в других, разный уровень thread-safety.

---

## Решение: единая иерархия

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ←── НОВЫЙ БАЗОВЫЙ КЛАСС
        │
        ├── LoggerManager       (BatchBuffer,       key=level/scope)
        │       │
        │       └── ErrorManager  (_level_to_channel, severity routing)
        │
        └── RouterManager       (AsyncSender,       channel+msg dispatchers)
```

`ChannelRoutingManager` пишет один раз:
- `ChannelRegistry` — thread-safe (RLock), работает с `IChannel`
- `Dispatcher` — маршрутизация ключ → обработчик
- `IBufferStrategy` — pluggable буферизация
- `normalize_config()` — Dict at Boundary
- `ChannelRoutingConfig` — базовый RegisterBase-конфиг

Каждый наследник **настраивает**, но **не переписывает**.

---

## Иерархия интерфейсов каналов

```
IChannel (channel_routing_module)
    │  name, channel_type, write(), close(), get_info()
    │
    ├── ILogChannel (logger_module)
    │       close() — abstract
    │       Реализует: LogChannel → FileChannel / ConsoleChannel / HttpChannel
    │
    └── IMessageChannel (router_module)
            send() — abstract (write = alias)
            poll() — abstract
            start/stop_listening()
            Реализует: MessageChannel → QueueChannel / SocketChannel
```

**Все каналы фреймворка совместимы с `ChannelRegistry`** — единый реестр для всего.

---

## Конфигурация через RegisterBase

```
ChannelRoutingConfig (RegisterBase)
    manager_name: str
    channels: Dict[str, dict]   ← общая секция
    build() → (name, dict)

    ├── LoggerManagerConfig (будущий)
    │       default_level, batch_size, scopes
    │
    └── ErrorManagerConfig
            critical_file_path, error_file_path, warnings_file_path
            include_stacktrace, enable_batching, batch_size
            channels ← унаследован (точка расширения для Telegram/Slack)
```

`normalize_config()` обрабатывает любой формат:
```python
normalize_config(None)         # → {}
normalize_config({"key": v})   # → {"key": v}
normalize_config(MyConfig())   # → config.build()[1] → dict
```

---

## Стратегии буферизации

| Стратегия | Когда использовать | Используется в |
|---|---|---|
| `DirectBuffer` | Тесты, синхронные операции, низкая нагрузка | Тесты CRM |
| `BatchBuffer` | Запись в файлы, агрегация логов (I/O-bound) | `LoggerManager` |
| `AsyncSenderBuffer` | Message-очереди, низкая задержка | Тесты CRM |
| `AsyncSender` (в RouterManager) | Полный pipeline с middleware | `RouterManager` |

### Потолок и потери (Ф0.3)

Обе очередные стратегии ограничены и считают потери — «сток не успевает» не бывает молчаливым:

| Стратегия | Потолок | Счётчики в `stats` |
|---|---|---|
| `BatchBuffer` | `BatchConfig.max_pending` на канал (дефолт 10 000; `0` — без потолка) | `dropped`, `dropped_by_channel`, `flush_failed`, `flush_failed_by_channel`, `in_flight`, `in_flight_records`, `flush_skipped_busy`, `max_pending`, `overflow_policy` |
| `AsyncSenderBuffer` | `queue_size` на очередь | `dropped` |

**Память росла не в очереди.** Deque держит триггер `max_size`, а вот число пачек «в полёте» не держало ничто: медленный сток не мешал каждому следующему потоку начать свой сброс. Поэтому у `BatchBuffer` два механизма, а не один:

1. `_in_flight` — **один сбрасывающий поток на канал**; остальные копят (`flush_skipped_busy` считает отклонённые попытки);
2. `max_pending` — потолок накопленного, срабатывающий **только пока сток занят**. При свободном стоке переполнение лечится сбросом, поэтому `max_pending < max_size` не превращает батчинг в сэмплирование на здоровой системе.

Политика переполнения:

- `drop_oldest` (дефолт) — кольцо: выбрасывается самая старая запись канала. Ближний к падению контекст ценнее давнего;
- `drop_newest` — пачка замораживается, новая запись не принимается.

**Цену стока платит эмитент, а не фоновый поток** (резидуал F4 фазы Ф0). Сбросом занимается тот поток, чей `enqueue()` совпал с триггером, — то есть обычно прикладной код, а не таймер буфера. Длительность `flush_fn` (запись в файл, ротация, консоль) целиком лежит на нём. Это не новость Ф0.3, а свойство батчера с самого начала; `_in_flight` его лишь заострил: пока один поток в полёте, остальные копят и переполнение становится заметнее. Практическое следствие: **медленный сток тормозит не логгер, а вызывающий код**, и симптом выглядит как «просело приложение», а не «просели логи». Диагностика — `flush_skipped_busy`, `in_flight`, `in_flight_records` в `introspect.observability`.

**Чего `flush_fn` делать нельзя** (резидуал F2): вызывать `buf.flush(<тот же канал>)`. Канал на время вызова помечен `_in_flight`, поэтому такой сток блокирует сам себя на полный барьер — замерено ровно `DEFAULT_FLUSH_BARRIER_TIMEOUT` (5.00 с) на вызов, с ростом `flush_timeouts` и без записи. Сбрасывать другой канал допустимо. Ни один сток фреймворка так не делает; предупреждение здесь потому, что симптом на буфер не указывает.

**Записи после `stop()`** (резидуал F3) принимаются в очередь — явный `flush()` их ещё доставит — но считаются в `enqueued_after_stop`. Раньше они оседали полностью молча: `pending={'Z': 3}` при `dropped=0` и `dropped_at_stop=0` (тот считает только остаток на момент самой остановки). Ненулевое значение означает «кто-то ещё пишет в закрытую плоскость».

**Уборка ушедших каналов** (резидуал F6): `forget_channel(name)` снимает очередь и отметку времени канала, которого больше нет; менеджер зовёт её из `set_sink_enabled(..., False)` и `disable_module_logging`. Счётчики потерь по каналу при этом **сохраняются** — их история обязана пережить снятие приёмника. Отказ (`False`) означает «в очереди есть неотправленное»: молча выбросить его нельзя.

**Две разные потери названы по-разному:**

| Счётчик | Что значит |
|---|---|
| `dropped` / `dropped_by_channel` | не приняли на входе — потолок при занятом стоке |
| `flush_failed` / `flush_failed_by_channel` | отдали в сток, а сток не принял (канала нет, `write` вернул `status: error`) |

`flush()` / `flush_all()` / `stop()` — **барьер**: если канал сбрасывает другой поток, вызов ждёт его и забирает накопленное следом (таймаут `DEFAULT_FLUSH_BARRIER_TIMEOUT`, исчерпание считается в `flush_timeouts`). Оппортунистический путь из `enqueue` и таймера — `wait=False`, занятый канал просто пропускается. Барьерность несёт два контракта: порядок «контекст раньше ошибки» и полноту слива при остановке (остаток после двух проходов — `dropped_at_stop`, а не тишина).

Контракт `flush_fn`: возврат `int` = число **фактически принятых** записей. Значение вне `[0, len(batch)]` — нарушение контракта стоком: считается в `flush_contract_violations`, пачка НЕ засчитывается доставленной. Возврат `None` (прежний контракт) — «сток не рапортует», пачка считается доставленной. Без этого `total_flushed` означал бы «отдано», а не «записано», и счётчики показывали бы здоровую плоскость при стопроцентной потере.

Инвариант учёта (проверяется тестом `test_batch_buffer_limits.py`), честен **в любой момент**, включая активный сброс:

```
total_enqueued == total_flushed + Σ pending + dropped + flush_failed + in_flight_records
```

Для логгера и менеджера ошибок потолок задаётся секцией `observability`
(`batch_max_pending`, `batch_overflow_policy`) и меняется на живой системе через
`config.reload`. Прочитать фактическое состояние — команда `introspect.observability`
(секция `counters`).

> **Осторожно со счётчиком `urgent_flush_requests`:** это число *запросов* сброса по
> приоритету, а не записанных пачек. Фактический сброс идёт вне lock-а, и при гонке
> пачку может осушить соседний поток — значение может превысить `total_batches`.

> **Почему RouterManager не использует AsyncSenderBuffer?**
> `AsyncSenderBuffer` работает с pre-resolved каналами: `enqueue(channel_name, data)`.
> RouterManager буферизует ПОЛНЫЙ pipeline: `enqueue(msg) → middleware → resolve → send`.
> Это намеренное архитектурное решение (ADR-015): AsyncSender в RouterManager буферизует
> более сложную цепочку, включая middleware-трансформации.

---

## Публичный API

### `ChannelRoutingManager`

| Метод | Вход | Выход | Описание |
|---|---|---|---|
| `initialize()` | — | bool | Запустить dispatcher + buffer |
| `shutdown()` | — | bool | flush → stop → close channels |
| `register_channel(ch)` | IChannel | bool | Thread-safe регистрация |
| `unregister_channel(name)` | str | bool | Thread-safe удаление |
| `get_channel(name)` | str | IChannel? | Найти канал по имени |
| `get_all_channels()` | — | List[IChannel] | Все каналы |
| `register_route(key, ch_name)` | str, str | bool | Ключ → канал |
| `register_broadcast(key, names)` | str, List[str] | bool | Ключ → несколько каналов |
| `route(data, key_field?)` | dict | dict | Маршрутизировать данные |
| `flush()` | — | None | Сбросить buffer |
| `get_stats()` | — | dict | channels + buffer + routing |
| `set_sink_enabled(name, on)` | str, bool | bool | Снять/вернуть приёмник на лету (Ф0.6) |
| `add_tap(ch, min_level=, name=)` | IChannel | str | Приёмник **всех** записей ≥ порога, переживает `reconfigure()` |
| `remove_tap(name)` | str | bool | Отключить tap |
| `_fallback_log(level, msg)` | str, str | None | Последний рубеж через stdlib |
| `_recreate_channel(name)` | str | bool | **Хук наследника:** собрать канал по имени из своего конфига |
| `_on_channels_changed()` | — | None | **Хук наследника:** состав каналов изменился в рантайме (Ф0.8) |
| `_validate_config(config)` | dict | None | **Хук наследника:** разобрать новый конфиг ДО разрушения; бросает при негодном (R9) |

### `reconfigure` — сначала проверить, потом разрушать (R9)

Порядок внутри `reconfigure` и есть гарантия: **разбор нового конфига стоит до
`_close_all_channels()`**. Раньше было наоборот — разбор жил у наследника внутри
`_rebuild_from_config`, то есть уже после закрытия каналов, и одна опечатка в
значении поля стоила всего реестра: воспроизведено на боевой раскладке
логгера — 12 каналов → 0, `system.log` 0 байт. Отказ применить конфиг
превращался в разрушение наблюдаемости, включая возможность узнать, что
случилось.

Два рубежа защищают от **разного**, и подменять один другим нельзя:

| Рубеж | Что ловит | Итог |
|---|---|---|
| `_validate_config` | конфиг не разобрался (опечатка, неверный тип) | каналы **не тронуты вовсе**, те же объекты |
| откат | конфиг разобрался, но пересборка развалилась (отказ ОС, битый путь) | каналы **пересозданы** из последнего принятого конфига |

Различить два исхода по `names()` невозможно — набор имён одинаков. Различает
тождество объектов канала, на нём и стоят тесты.

Откат берёт **последний принятый** конфиг (`_last_applied_config`), а не
последний поданный: иначе после отвергнутой попытки система восстанавливалась бы
из конфига, который сама только что признала негодным. Наследник, резолвящий
конфиг сам и передающий в базу `config=None` (так делает `LoggerCore`), обязан
выставить слепок в своём `__init__` — иначе второй рубеж у него мёртв.

Восстанавливается **конфиг**, а не рантайм-надстройки над ним: каналы,
добавленные в обход конфига (`enable_module_logging`), в слепок не входят и
теряются. Записано тестом, а не подразумевается.

### Control-plane наблюдаемости (Ф0.6)

`set_sink_enabled` живёт в базе, потому что операция одна и та же у всех трёх
плоскостей — логов, ошибок и статистики. До Ф0.6 она была только у логгера:
оператор мог снять приёмник логов, но не приёмник статистики.

**Выключение полностью generic** — закрыть канал и снять с реестра; откуда канал
взялся, знать не нужно. **Включение** требует пересоздать канал из конфига
конкретного менеджера, и это единственная часть на наследнике — `_recreate_channel`.
База отвечает `False` («не умею») вместо молчаливого `True`: оператор увидит
`success=False`, а не «включил» при выключенном приёмнике.

> ⚠️ **`RouterManager` тоже наследует `set_sink_enabled` — и это транспорт, а не
> плоскость наблюдаемости.** Поэтому команда `logger.sink.enable|disable` ищет цель
> по **whitelist'у** `logger|error|stats` (`_SINK_ADDRESSABLE_MANAGERS` в
> `builtin_commands.py`), а не через `hasattr`. Резолв «любой менеджер с методом»
> дал бы способ одной командой тихо снять message-канал и отрезать процессу IPC.

`_on_channels_changed()` вызывается **только когда состав действительно
изменился** — неудачный toggle (неизвестное имя) хук не дёргает: «ничего не
произошло» не должно выглядеть как событие, иначе опечатка оператора в имени
канала стоила бы наследнику полного сброса кэша. `LoggerCore` вешает на него
инвалидацию `_decision_cache` (Ф0.8) — **профилактика, а не починка симптома**:
сегодня решение `should_log` не зависит от состава каналов, поэтому стейла не
бывает; с Ф2.2 в то же решение попадёт резолв `effective_channels`, и без хука
`logger.sink.disable` оставлял бы ответ про уже снятый канал.

Tap'ы (`add_tap`) отличаются от каналов реестра тем, что не участвуют в
маршрутизации и **переживают `reconfigure()`** — подписка на tail не рвётся при
hot-reload. Порог задаётся уровнем; у плоскостей без уровней (статистика) записи
считаются самыми низкими по важности и проходят при пороге `"DEBUG"`.

Числа важности (`LEVEL_ORDER` / `severity_of` / `is_error_level`) лежат в
[`levels.py`](levels.py) этого модуля, а не в `logger_module`: они нужны всем троим,
и база не имеет права зависеть от своего потомка.

**Ф3.1 — числа словаря OpenTelemetry.** `SEVERITY_NUMBERS` = `SeverityNumber`
спеки OTel (DEBUG 5, INFO 9, WARNING 13, ERROR 17, CRITICAL 21), и это ЕДИНСТВЕННЫЙ
порядок в слое: своих рангов 0…4 больше нет. Число **выводится** из имени уровня —
в записи его не возят, материализуют только на границе внешнего потребителя.

Две функции вместо одной — по одной на позицию, и дефолты у них противоположные:

| Функция | Позиция | «Не понял» → |
|---|---|---|
| `severity_of` | сравнение как есть | `UNKNOWN_SEVERITY` (−1), маскировать нельзя |
| `record_severity` | уровень ЗАПИСИ | `DEBUG_SEVERITY` (5) — доставить как самую низкую |
| `threshold_severity` | ПОРОГ приёмника | `UNSPECIFIED` (0) — пропускать всё (fail-open) |

До Ф3.1 обе позиции обслуживала одна функция, и работало это только потому, что
0 был числом DEBUG. Имя уровня проверяется на границах (`normalize_level_name`):
валидатор `min_level`, аргумент `log.tail.subscribe` и `observability.tail.subscribe`.
`WARN`/`FATAL` — законные синонимы, живут отдельной таблицей и в горячую не попадают.

### `ChannelRoutingConfig`

| Поле | Тип | Описание |
|---|---|---|
| `manager_name` | str | Имя менеджера |
| `channels` | Dict[str, dict] | Дополнительные каналы |
| `build()` | → (str, dict) | Для normalize_config() |

---

## Быстрый старт — создать новый менеджер

```python
from channel_routing_module import (
    ChannelRoutingManager, IChannel,
    BatchBuffer, BatchConfig, ChannelRoutingConfig,
)
from data_schema_module import register_schema, FieldMeta
from typing import Annotated, List, Dict, Any


# 1. Создать конфиг
@register_schema("MyManagerConfig")
class MyManagerConfig(ChannelRoutingConfig):
    manager_name: str = "MyManager"
    output_path: str = "data/output.jsonl"
    batch_size: Annotated[int, FieldMeta("Размер батча", min=1, max=10000)] = 100

    def build(self) -> tuple[str, dict]:
        return (self.manager_name, {
            "channels": {"output": {"type": "file", "path": self.output_path}},
            "batch_size": self.batch_size,
        })


# 2. Создать канал
class MyChannel(IChannel):
    def __init__(self, name: str, path: str):
        self._name = name
        self._path = path

    @property
    def name(self) -> str: return self._name

    @property
    def channel_type(self) -> str: return "file"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with open(self._path, "a") as f:
            import json; f.write(json.dumps(data) + "\n")
        return {"status": "success", "channel": self._name}

    def close(self) -> None: pass


# 3. Создать менеджер
class MyManager(ChannelRoutingManager):
    def __init__(self, config=None):
        cfg = MyManagerConfig() if config is None else config

        super().__init__(
            "MyManager",
            config=cfg,
            buffer_strategy=BatchBuffer(
                flush_fn=self._on_flush,
                config=BatchConfig(max_size=100, flush_interval=1.0),
            ),
            dispatcher_key_field="event_type",
        )
        self._output_ch = MyChannel("output", "data/output.jsonl")

    def _on_flush(self, channel: str, batch: List[Dict]) -> None:
        ch = self._channel_registry.get(channel)
        if ch:
            for item in batch:
                ch.write(item)

    def initialize(self) -> bool:
        result = super().initialize()
        if result:
            self.register_channel(self._output_ch)
            self.register_route("data_event", "output")
            self.register_route("error_event", "output")
        return result

    def emit(self, event_type: str, payload: dict) -> None:
        self.route({"event_type": event_type, **payload})


# 4. Использовать
mgr = MyManager()
mgr.initialize()
mgr.emit("data_event", {"value": 42, "sensor": "A1"})
mgr.emit("error_event", {"code": "E_001", "msg": "sensor offline"})
mgr.flush()
mgr.shutdown()
```

---

## Примеры из реальных наследников

### LoggerManager — BatchBuffer + scope routing

```python
class LoggerManager(ChannelRoutingManager, ILoggerManager):
    def __init__(self, config=None):
        super().__init__(
            "LoggerManager",
            buffer_strategy=BatchBuffer(flush_fn=self._flush_batch),
            dispatcher_key_field="level",
        )
        self._buffer = BatchBuffer(...)

    def info(self, msg, module="main"):
        self.log(LogScope.BUSINESS, LogLevel.INFO, msg, module)

    def log(self, scope, level, message, module, **extra):
        record_dict = LogRecord(...).to_dict()
        channels = scope_config.channels
        for ch_name in channels:
            self._buffer.enqueue(ch_name, record_dict)
```

### ErrorManager — _level_to_channel + level routing

```python
class ErrorManager(LoggerManager):
    def initialize(self) -> bool:
        result = super().initialize()
        self._setup_level_routes()
        return result

    def _setup_level_routes(self) -> None:
        # Прямой маппинг: O(1) lookup вместо scope-based routing
        self._level_to_channel = {
            "CRITICAL": "critical_file",
            "ERROR":    "errors_file",
            "WARNING":  "warnings_file",
        }

    def log(self, scope, level, message, module, **extra):
        channel_name = self._level_to_channel.get(level.value)
        if channel_name:
            # КРИТИЧЕСКИ ВАЖНО: level routing РЕАЛЬНО вызывается
            self._buffer.enqueue(channel_name, record_dict)
        else:
            LoggerManager.log(self, ...)  # DEBUG/INFO → scope-based
```

### RouterManager — channel_dispatcher + message_dispatcher

```python
class RouterManager(ChannelRoutingManager):
    def __init__(self, ...):
        super().__init__("RouterManager", ...)
        self._sender = AsyncSender(...)      # Полный pipeline с middleware
        self.channel_dispatcher = self._dispatcher  # alias из CRM
        self.message_dispatcher = Dispatcher(...)   # для ВХОДЯЩИХ

    def register_channel(self, channel):
        # Override: inject _attach_logger, NO auto-dispatcher registration
        channel._attach_logger(self._log_warning, self._log_error)
        return self._channel_registry.register(channel)

    def register_route(self, key, channel_name):
        # Name-returning handler (не write-handler как в CRM)
        return self.channel_dispatcher.register_handler(
            key, handler=lambda msg: channel_name
        )
```

---

## Структура модуля

```
channel_routing_module/
├── interfaces.py             — IChannel, IBufferStrategy, IChannelRoutingManager
├── __init__.py               — публичный API
├── README.md                 — этот файл
├── STATUS.md                 — карточка здоровья
├── DECISIONS.md              — ADR-013…016, ADR-108
│
├── core/
│   ├── channel_routing_manager.py  — ChannelRoutingManager (BaseManager + ObservableMixin)
│   ├── channel_registry.py         — ChannelRegistry (thread-safe, generic IChannel)
│   ├── config.py                   — ChannelRoutingConfig(RegisterBase)
│   └── config_normalizer.py        — normalize_config(None|dict|RegisterBase → dict)
│
├── buffers/
│   ├── direct_buffer.py            — DirectBuffer (прямой вызов, для тестов)
│   ├── async_sender_buffer.py      — AsyncSenderBuffer (PriorityQueue + worker thread)
│   └── batch_buffer.py             — BatchBuffer (deque + lock + timer flush)
│
└── tests/
    ├── test_channel_routing_manager.py  — 18 тестов
    ├── test_channel_registry.py         — 17 тестов
    └── test_buffers.py                  — 23 теста
```

---

## Зависимости

```
channel_routing_module
    ← base_manager     (BaseManager, ObservableMixin, IBaseManager)
    ← dispatch_module  (Dispatcher, DispatchStrategy)
    ← data_schema_module (RegisterBase, FieldMeta, register_schema)

Зависит от:       base_manager, dispatch_module, data_schema_module
НЕ зависит от:    router_module, logger_module, error_module
Используется в:   logger_module, error_module, router_module
```

**Нет циклов**: `channel_routing_module → dispatch_module → base_manager`

---

## Запуск тестов

```bash
cd multiprocess_framework/refactored

# Только channel_routing_module (58 тестов)
pytest modules/channel_routing_module/tests/ -v

# Вся иерархия (155 тестов)
pytest modules/channel_routing_module/tests/ \
       modules/logger_module/tests/ \
       modules/error_module/tests/ \
       modules/router_module/tests/ -v
```

Ожидаемый результат: **155 passed** — все тесты зелёные.

---

## Что было унифицировано (итог)

| До | После | Выигрыш |
|---|---|---|
| 3 разных `ChannelRegistry` | Один в CRM | thread-safety везде |
| 2 разных буфера (`AsyncSender`, `BatchManager`) | 3 стратегии в CRM | выбор стратегии без дублирования кода |
| `LogConfig` (dataclass), `ErrorManagerConfig(RegisterBase)`, RouterManager без конфига | `ChannelRoutingConfig(RegisterBase)` как база | единый путь в ConfigManager |
| `_setup_level_routes()` регистрировал маршруты которые никогда не вызывались | `ErrorManager.log()` переопределён, level routing РЕАЛЬНО работает | исправлена скрытая архитектурная ошибка |
| `channels: Dict` без lock в LoggerManager | `_channel_registry` (RLock) из CRM | thread-safe |
| `IMessageChannel` и `ILogChannel` — изолированные иерархии | `IMessageChannel(IChannel)`, `ILogChannel(IChannel)` | единый тип для ChannelRegistry |
| Новый менеджер = копирование кода из 3 мест | Новый менеджер = наследование CRM | 10 минут вместо дня |
