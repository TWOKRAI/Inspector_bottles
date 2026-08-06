# logger_module — Статус рефакторинга

## Текущий этап: 5 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | CRM; BatchBuffer; удалены LogDispatcher, legacy batcher/, свойства channels/batcher |
| Тесты | 7 | ~30 тестов; стресс BatchBuffer и расширенное scope routing — по желанию |
| Документация | 9 | README, DECISIONS.md (ADR-LOG-001…003), §6.5 в ARCHITECTURE.md |
| Связанность | 9 | Наследует ChannelRoutingManager; зависит от channel_routing_module |
| Дублирование | 10 | Нет: registry, BatchBuffer, Dispatcher — из CRM |
| Работоспособность | 8 | BatchBuffer + scope routing; ErrorManager без LogDispatcher |

## Обновление 2026-08-03 (Ф2.2 — иерархия имён)

- **`core/name_hierarchy.py`** (новый, ~180 строк): резолв «префикс имени → уровень/приёмники»
  по самому длинному совпадению, со своим кэшем. Чистая функция от таблицы правил —
  проверяется без подъёма логгера (26 тестов, `tests/test_name_hierarchy.py`).
- **`LoggerRuleSchema`** + поле `LoggerManagerConfig.loggers` (по умолчанию пусто → поведение
  бит-в-бит прежнее); ручка задаётся из секции `observability.loggers`.
- **`LoggerCore.effective_level()` / `effective_channels()`** — публичный резолв для пульта.
  Гейт: правило имени сильнее скоупа (решение владельца 2026-08-03), включая `enabled`.
  Severity-путь `ErrorManager` правила не спрашивает — инвариант «ошибка не теряется» цел.
- Повод — числа живого прогона 2026-08-03: из 384 per-module файлов непустыми 4, и все
  четыре по совпадению имени процесса с ключом файла. Ручки «в какой файл» не существовало.
- 22 теста проводки (`tests/test_name_routing.py`, судят по содержимому файлов и счётчикам);
  10 слом-инъекций, все красные.

## Обновление 2026-07-26 (G4-live)

- **`adapters/std_facade.py`:** `StdLoggerFacade` + `get_std_logger(module)` — мост из
  stdlib-стиля (`logger.warning("%s", x)`) в `LoggerManager`. Повод: живой прогон показал,
  что 44 файла GUI-слоя прототипа пишут через `logging.getLogger(__name__)`, у которого в
  процессе нет ни одного хендлера → записи не доходили ни до `logs/<proc>/*.log`, ни до
  консоли. Без менеджера фасад пишет в stdlib (фолбэк), а не молчит: тишина — второй
  проглот той же ошибки. 18 тестов (`tests/test_std_facade.py`).
- Первые потребители: `topology_bridge.py` (заменил локальный шим), `processes/presenter.py`.
  Остальные 43 файла — задача H.4.

## Обновление 2026-04-01

- Резолв относительных путей логов: **`core/log_paths.py`**, поле **`LoggerManagerConfig.log_directory`**; файлы по умолчанию не создаются в каталоге пакета при запуске из `modules/` (см. **ADR-111**).

## Обновление 2026-04-02

- **`LoggerManagerConfig`:** без `from_dict` / `from_yaml` / `get_scope_config`; загрузка через **`model_validate`**, fallback scope — **`LoggerManager._scope_schema`** (см. **ADR-112**).

## Обновление 2026-04-03

- **`logger_manager_config.py`:** дефолтный порог **INFO** для **`LoggerScopeSchema`** и скоупов **BUSINESS** / **PERFORMANCE** задаётся как **`_LEVEL_ORDER[1]`** (один источник с порядком уровней в **`should_log`**); отдельное поле **`log_level`** у конфига не используется — глобальный уровень задаёт **`default_level`**, **BUSINESS** при необходимости подставляется в **`ManagersConfig.from_log_dir`**.

## Обновление 2026-04-09 (Фаза 3 cleanup)

- Удалены **`LogDispatcher`** и пакет **`batcher/`**; **`LogRecord`** в **`core/log_types.py`** (см. **ADR-LOG-001…003**).
- Убраны backward compat: **`channels`**, **`batcher`**, **`self.dispatcher`**.

## Что сделано в CRM-миграции (Фаза 2–3)

- [x] `ILogChannel(IChannel)` — унифицированная иерархия каналов
- [x] `LogChannel(ILogChannel)` — `name`, `channel_type` как `@property`; `FileChannel`, `ConsoleChannel`, `HttpChannel` наследуют
- [x] `LoggerManager(ChannelRoutingManager, ILoggerManager)` — убраны дублирующие реализации registry/buffer
- [x] `self._channel_registry` из CRM вместо `channels: Dict` (был без lock)
- [x] `BatchBuffer` из CRM вместо `BatchManager` (legacy batcher удалён)
- [x] `_resolve_log_config()` — None | dict | LoggerManagerConfig | `build()` → **LoggerManagerConfig** (SchemaBase)
- [x] Конфиги: `configs/logger_manager_config.py` — **LoggerManagerConfig** extends **ChannelRoutingConfig**
- [x] `initialize()` / `shutdown()` — только CRM-компоненты (`_dispatcher`, `_buffer`, registry)

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (config_dict, _route_via_router)
- [x] Этап 1: Модуль запускается — LoggerManager.initialize() работает
- [x] Этап 2: interfaces.py, README, encoding headers, интеграция с message_module
- [x] Этап 3: level-based routing в ErrorManager; cleanup LogDispatcher / batcher
- [x] Этап 4: LoggerManager наследует ChannelRoutingManager; ILogChannel(IChannel)
- [x] Этап 5: Документация и удаление legacy dispatcher/batcher (текущий шаг плана #5)
- [ ] Этап 6: Graceful shutdown — flush() перед остановкой + router unsubscribe
- [ ] Этап 7: Unit-тесты — покрытие > 85%, стресс-тест BatchBuffer под нагрузкой
- [ ] Этап 8: Полная интеграция с process_manager_module

## Известные проблемы

- На Windows `RotatingFileHandler` может падать при ротации общего файла (WinError 32). Для таких случаев в `ModuleConfig` / `ChannelConfig` есть `rotate: false` → `FileHandler` (см. ADR-051, `app_config.processor_frames`). Сам сбой ротации (fail-open — запись продолжается в текущий файл) теперь виден: `_SafeRotatingFileHandler` считает сбои подряд и не чаще раза в 60с пишет WARNING с именем файла, размером и числом неудач — раньше `PermissionError` глушился молча без счётчика и предупреждения (живая находка 2026-07-21, `messages.log` вырос до 645 МБ незамеченным).
- **Поток, уже вошедший в блокирующую запись в консоль, ничем не ограничен (R2, остаток).** Ожидание ОЧЕРЕДИ ограничено 0.25 с и отбросы считаются, но первый поток, который уже внутри `stream.write()`, остаётся заблокированным навсегда. Полное ограничение требует выноса записи в отдельный поток-писатель — размен «консоль переживает падение процесса» на «консоль ограничена». Решение владельца, не техническая недоделка.
- **Рост числа файлов ограничен, разовая уборка — нет (Ф0.7).** Ротация держит каждый файл, ретеншен (`retention_days` / `retention_total_mb` / `compress_rotated`) держит каталог, но метёт **свой подкаталог** — `logs/<имя процесса>/`. Каталоги давно умерших процессов не метёт никто: они не растут, но и не исчезают. Это разовая уборка, вне объёма Ф0.7.
- **Счётчик `retention_delete_failures` может завышать при гонке двух подметальщиков за один каталог.** Детерминированный случай Windows delete-pending (удаление отказано, но файла уже нет) разобран по факту, а не по типу исключения, и в отказы не попадает. Остаточное окно между «удаление соседа началось» и «файл исчез» закрыть проверкой существования нельзя. Результат уборки это не портит — только завышает счётчик отказов. В проде сценарий не воспроизводится: `expand_observability` отдаёт ретеншен только `logger`.
- Стресс-тест BatchBuffer под многопоточной нагрузкой не написан.
- **Цена синхронного пути (Ф0.9 → закрыто Ф7.4).** Пункт был про сброс пачки перед записью
ошибки: 1.3 мс p50 / 1.6 мс p95 в потоке-эмитенте, «окончательно снимается Ф7.2/Ф7.3».
Снято раньше и другим способом — **батчинг убран целиком** (Ф7.4): сбрасывать нечего,
цены нет. Запись синхронна на всех уровнях; замер, живая пара и разбор — ADR-LOG-008.
- **Floor ошибок — диагностический сигнал, а не норма.** `errors_floor.jsonl` (JSON Lines, рядом с логами) появляется **только** когда штатный маршрут не принял ни одного канала: приёмники выключены конфигом, сняты `logger.sink.disable` или все `write` упали. Непустой floor означает «маршрут ошибок сломан». Счётчик — `get_stats()["errors_to_floor"]`. Дублей floor не создаёт: он пишет строго при нуле принявших каналов (это и отличает вариант B от отклонённого варианта A с отдельным аварийным файлом поверх обычного маршрута). Видимый путь наружу (Ф0.3): `get_stats()` отдаёт `errors_to_floor` и секцию `error_floor` (`path`/`written`/`failures`), команда `introspect.observability` — то же самое у живого процесса.

## История изменений

| Дата | Что сделано | Этап |
|---|---|---|
| 2026-03-11 | Начальное состояние, STATUS.md создан | 0 |
| 2026-03-12 | interfaces.py, bugs fixed, README, encoding headers | 2 |
| 2026-03-12 | BatchManager thread-safe, LogDispatcher fix, level-based routing | 3 |
| 2026-03-12 | CRM Фаза 2: LoggerManager(ChannelRoutingManager), ILogChannel(IChannel), BatchBuffer | 4 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
| 2026-03-31 | ADR-108: убран избыточный `build()` у `LoggerManagerConfig` (наследует `SchemaMixin.build`) | — |
| 2026-04-09 | Удалены LogDispatcher и batcher/; LogRecord → log_types.py; ADR-140…142 | 5 |
| 2026-07-21 | `_SafeRotatingFileHandler`: счётчик сбоев ротации + троттлированный WARNING (видимость систематического отказа, fail-open не тронут) | 5 |
| 2026-07-26 | Ф0.1: `buffer_priority()` + `priority="urgent"` для ERROR/CRITICAL — закрыто окно потери crash-лога (было до `batch_interval`). Временно, снимается Ф0.9. Размен измерен, см. «Известные проблемы» | — |
| 2026-07-26 | **Ф0.9 (floor, вариант B):** `error`/`critical` синхронно мимо буфера + `ErrorFloor` (`errors_floor.jsonl`) при нуле принявших приёмников. `buffer_priority()` из Ф0.1 удалён, заменён предикатом `is_error_level()`. Инвариант 1 плана: одно место, без дублей, конфиго-независимо, запись полная (traceback + extra) | — |
| 2026-07-26 | **Ф0.3:** потолок буфера операбелен из конфига (`batch_max_pending`, `batch_overflow_policy` — и в секции `observability`); `get_stats()` перестал прятать `errors_to_floor`; счётчики трёх плоскостей вышли наружу командой `introspect.observability` | — |
| 2026-07-26 | **Ф0.4:** запись в нерезолвящийся канал больше не теряется молча — `unresolved_channel_records` / `unresolved_channels` + `channel_write_errors` / `channel_write_errors_by_channel` в `get_stats()` и в `introspect.observability`, одноразовый WARNING на имя. Оба `except: pass` вокруг `ch.write()` заменены счётчиком. Счётчики потерь под отдельным локом (без него 12×3000 записей дают 29 261 из 36 000). Тесты: 10 контрактных (независимый tester, от acceptance, без чтения кода) + 7 авторских на гонки/реентерантность/floor | — |
| 2026-07-26 | **Ф0.5:** контекст логирования разделён на два слоя. `push_context`/`pop_context` стали потоковыми (ContextVar → изоляция и между потоками, и между asyncio-тасками); добавлен `set_base_context`/`clear_base_context` для фактов про процесс целиком. Причина второго слоя: единственный производственный вызов кладёт `proc_name` из главного потока, а пишут воркеры — чисто потоковый контекст молча выкинул бы `proc_name` из их записей. `process_module` переведён на базу, `process_lifecycle` — на `clear_base_context`. Тесты: 10 контрактных (независимый tester, гонка сделана воспроизводимой через `sys.setswitchinterval`) + 7 авторских | — |
| 2026-07-26 | **Ф0.7:** ретеншен и компрессия каталога логов — `retention_days` / `retention_total_mb` / `compress_rotated` (в `LoggerManagerConfig` и в секции `observability`, применяются hot-reload'ом), `enforce_log_retention()` в `log_channel.py`. Обе политики выключены по умолчанию. Порядок: возраст → компрессия → потолок (потолок считает вес ПОСЛЕ сжатия); возраст переносится на архив, иначе компрессия молча отключала бы удаление по возрасту. Активные файлы и `errors_floor.jsonl` неприкосновенны. Пять счётчиков в `get_stats()` и `introspect.observability`. Тесты: 12 контрактных (независимый tester) + 16 авторских; десять точечных сломов дают ровно ожидаемую красноту | — |
| 2026-07-27 | **R2 (резидуал Ф0.1, адресат 0.7):** предел ожидания занятой консоли — `ConsoleChannel` берёт лок записи с таймаутом 0.25 с и отбрасывает запись со статусом `error` (на нём завязан пол ошибок Ф0.9). Затык консоли больше не выстраивает за собой все потоки-эмитенты и не забирает файловые каналы. Счётчики `console_writes_dropped` / `console_slow_writes` — сумма по живым каналам, в `get_stats()` и `introspect.observability`; `get_info()` не берёт лок записи, поэтому диагностика доступна у застрявшего канала. Тесты: 7 контрактных (независимый tester) + 8 авторских, 5 сломов | — |

## Обновление 2026-08-05 (Ф7.1 — сэмплинг как процессор цепочки)

- **`core/sampling.py`** (новый, ~230 строк): `RateSampler` — процессор цепочки Ф4.1,
  ключ «уровень + текст», first-N → every-Mth, перезапуск всплеска по тишине. Стоит
  ВТОРЫМ, после редактора секретов (дроссель решает по тексту, текст обязан быть уже
  замаскированным). Часы — внедряемая зависимость, лока на горячем пути нет.
- **Четыре ручки** в `LoggerManagerConfig` и в секции `observability`
  (`sampling_first_n` / `sampling_every_mth` / `sampling_burst_reset_sec` /
  `sampling_max_level`). Выключен по умолчанию, выключенность выражена параметром (0).
  Имя уровня проверяется на границе конфига. Ошибки не сэмплируются никогда — потолок
  обрезан в коде, конфигом не поднимается.
- **Три счётчика наружу** (`records_sampled_out`, `sampler_keys_tracked`,
  `sampler_keys_saturated`) — в `get_stats()` и в реестре публикации; потеря считается
  цепочкой (`records_dropped_by_processor`), своего счётчика потерь дроссель не заводит.
  Пропущенная запись несёт `extra["sampled_skipped"]`.
- **Потолок карты ключей 4096 с насыщением**, а не чисткой (чистка вернула бы `first_n`
  всем ключам ровно в момент шторма) — ADR-LOG-007.
- **Цена измерена дельтой:** выключенный дроссель +0.10 мкс на записи; на штормовом
  повторе 3.60 мкс против 4.57 базовых, и до приёмника доехали 24 записи из 20 000; на
  уникальных ключах учёт стоит +0.80 мкс.
- **Тесты:** 16 контрактных от независимого тестировщика (`tests/test_sampling_contract.py`,
  писались без доступа к реализации) + 14 стражей автора (`tests/test_sampling_hazards.py`);
  14 слом-инъекций, все красные. Одна инъекция оказалась негодной и вскрыла ловушку алиаса
  (`self._sampler` против объекта в цепочке) — на неё заведён отдельный страж.
- **Вторая половина задачи** — дисциплина call-site: 11 из 12 точек `_log_debug`
  `router_manager.py` переведены на `lambda:` (двенадцатая — постоянная строка, ей
  замыкание было бы чистой ценой). Сторожит AST-страж
  `router_module/tests/test_debug_callsites_are_deferred.py`.
