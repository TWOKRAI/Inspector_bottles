# router_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary, ADR-013 CRM, ADR-015 AsyncSender)

## ADR-RTR-001 (was ADR-153): RouterManager наследует ChannelRoutingManager

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** RouterManager, LoggerManager, ErrorManager дублировали ChannelRegistry + Dispatcher.  
**Решение:** `RouterManager(ChannelRoutingManager)`. CRM даёт `_channel_registry`, `_dispatcher`, `_buffer` (не используется). RouterManager добавляет: AsyncSender (outgoing pipeline с middleware), AsyncReceiver, message_dispatcher.  
**Последствия:** Удалён локальный `core/_channel_registry.py` (мёртвый код после миграции). Единый паттерн для всех CRM-наследников. Для `channel_types` при опросе каналов суффикс — полный хвост после префикса `{process.name}_`, а не «последний сегмент по `_`», иначе ломаются имена вида `{process}_data_extra`.

## ADR-RTR-002 (was ADR-154): Name-returning handler pattern

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** CRM `register_route()` вызывает `channel.write()` напрямую. RouterManager'у нужен middleware pipeline перед send.  
**Решение:** `register_route("key", "channel_name")` регистрирует `lambda msg: "channel_name"`. `_resolve_channels()` получает строку → `_channel_registry.get(name)`.  
**Последствия:** Middleware всегда применяется. Dispatch возвращает имя канала, не результат отправки.

## ADR-RTR-003 (was ADR-155): Два dispatcher'а — channel + message

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Routing outgoing (в какой канал?) и handling incoming (какой handler?) — разные задачи.  
**Решение:** `channel_dispatcher` = CRM's `_dispatcher` (исходящие). `message_dispatcher` = отдельный Dispatcher (входящие).  
**Последствия:** Чёткое разделение; нет путаницы между routes и handlers.

## ADR-RTR-004 (was ADR-156): Thread-safe _stats с Lock

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `_do_send()` вызывается из main thread (sync `send()`) и AsyncSender thread (`send_async()`). `dict["key"] += 1` — не атомарная операция.  
**Решение:** `_stats_lock = threading.Lock()`. Helper `_inc_stat()` для всех мутаций. `get_stats()` читает снимок `_stats` под lock.  
**Последствия:** Корректные счётчики при параллельных sync и async отправках.

## ADR-RTR-005 (was ADR-157): IMessageChannel(IChannel) — осознанный cross-module import

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `interfaces.py` строка 17: `from ..channel_routing_module.interfaces import IChannel`. Это sibling-module relative import.  
**Решение:** Осознанная связь. IMessageChannel расширяет IChannel → QueueChannel совместим с CRM `ChannelRegistry` и `RouterManager`.  
**Последствия:** Единая иерархия каналов. Документировано как допустимое зацепление.

## ADR-RTR-006 (was ADR-158): Сохранение registration API (register_channel_handler, register_channel_scenario, cleanup)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Методы `register_channel_handler()`, `register_channel_scenario()`, `cleanup()` не имеют внешних вызовов на момент рефакторинга. Однако анализ `multiprocess_prototype_v2` показывает паттерн config-driven setup: каналы из конфига (`queues` dict в ProcessConfigBase), команды через `command_manager.register_command()`. Phase 8 STATUS.md предусматривает config-driven channel setup в RouterManager.  
**Решение:** Сохранить все registration-методы. Они образуют инфраструктуру для:
- `register_channel_handler` — аналог `command_manager.register_command()` для каналов
- `register_channel_scenario` — сценарная маршрутизация (multi-step pipelines)
- `cleanup()` — стандартный alias-паттерн для shutdown  
**Последствия:** LOC не сокращается на ~28 строк, но API готов к Phase 8 без breaking changes.

## ADR-RTR-007: Контракт routing-таблицы (`routing/`) — нормализация kind ДО таблицы

**Статус:** принято  
**Дата:** 2026-05-31  
**Контекст:** План `transport-router-hub` (P0.2) фиксирует контракт хаба — «`send` выбирает один канал по типу груза». Глобальное решение — [ADR-COMM-001](../../DECISIONS.md). Аудит (recon #1) показал, что на живых билетах поле `type` НЕ всегда соответствует целевому каналу: state-телеметрия несёт `type="event"`/`"command"`, но семантически — STATE (диспатч по `command="state.changed"`). Прямая таблица `MessageType → channel` на таких билетах промахивается.  
**Решение:** Подмодуль `router_module/routing/` — **декларация** контракта (без проводки в рантайм, она в P1):
- `MESSAGE_TYPE_TO_CHANNEL: dict[MessageType, str]` — база (type → channel-kind);
- `resolve_channel_kind(msg)` — **нормализация ДО таблицы**: сперва override по префиксу `command` (`COMMAND_PREFIX_TO_CHANNEL`, напр. `state.*` → `state`), затем таблица по `MessageType`; неизвестный `type` без покрытия → `UnknownMessageTypeError` (а НЕ тихий drop);
- `channel_name(process, kind)` → `f"{process}_{kind}"` («склейка» осей адрес × kind, совпадает с очередями `{proc}_system`/`{proc}_data`);
- `resolve_route(s)` → `RouteDecision(process, kind, channel, subpath)` — чистое ядро `send` будущего address-aware канала.
**Ключевое:** STATE — это **channel-kind**, выводимый из `command="state.*"`, а **НЕ** член enum `MessageType` (его не вводим — план запрещает новый `kind`). Новый Channel-Protocol тоже не вводится — address-aware канал будет подклассом существующего `MessageChannel` (P1.1).  
**Последствия:** Резолв канала работает на текущих (несогласованных по `type`) билетах без их немедленной миграции. `_resolve_channels` подключит `resolve_channel_kind` в P1.2. Контракт address-aware канала и решения по recon #2/#3/#4/#6 — в docstring `routing/address_aware_channel.py`.  
**Refs:** [ADR-COMM-001](../../DECISIONS.md), [ADR-COMM-004](../../DECISIONS.md), [plans/_archive/2026-05-31_transport-router-hub/plan.md](../../../plans/_archive/2026-05-31_transport-router-hub/plan.md)

## ADR-RTR-008: SocketChannel — внешний driver-доступ как обычный IMessageChannel

**Статус:** принято
**Дата:** 2026-06-01
**Контекст:** Нужен headless-доступ к бэкенду извне (driver под MCP — отлаживать backend без GUI/qt-mcp). Инвариант владельца: ВСЁ общение с бэкендом строго через `RouterManager`, без сайд-каналов. ProcessManager — отдельный OS-процесс; внешний процесс не подключить к shared `queue_registry` процессов. План `backend-control-mcp` P2 ([plan](../../../plans/_archive/2026-05-31_backend-control-mcp/plan.md), [дизайн](../../../plans/_archive/2026-05-31_backend-control-mcp/P2_socket_design.md)).
**Решение:** `SocketChannel(MessageChannel)` — серверный TCP-эндпоинт, **обычный** `IMessageChannel` (сиблинг `QueueChannel`), хостится в ProcessManager (`register_channel` — by-design extension). Делает ТОЛЬКО байтовый I/O (newline-JSON). Связь с router'ом — `SocketBridgeAdapter.on_inbound`: `router.request(msg)` (P0.5 request-response) → `router.send({type:response, channel:"backend_ctl", request_id, result})` → `_resolve_channels(channel=)` → `SocketChannel.send`. Внешний driver (`backend_ctl/`) шлёт те же router-сообщения, что GUI (общий билдер `message_module/builders/command_envelopes.py` — один источник правды GUI+driver), плюс reply-поля. Гейт `BACKEND_CTL=1` + bind 127.0.0.1.
**Ключевое:**
- `poll()` намеренно no-op: inbound — push через read-loop (`on_inbound`), не pull. Имя канала без префикса `{process}_` → `receive`-цикл его не опрашивает (и это верно).
- `request()` крутится в read-потоке сокета, резолвится в system-цикле PM (другой поток) → дедлок-контракт P0.5 соблюдён даром.
- Сокет = граница ровно Claude↔driver; кадры/SHM через сокет НЕ гоняем (Dict at Boundary).
- Совпадает с `transport-router-hub` P3 («ещё один IMessageChannel»), второй транспорт не плодим.
**Последствия:** Внешний доступ без нарушения инварианта «всё через router». В проде endpoint не существует (env-гейт). GUI-форма команд вынесена в билдер — `CommandSender` переведён на него (вывод байт-в-байт, регрессия зелёная). Остановка PID-specific (`teardown` закрывает канал + unregister), без глобального kill.
**Refs:** [plans/_archive/2026-05-31_backend-control-mcp/](../../../plans/_archive/2026-05-31_backend-control-mcp/plan.md), ADR-RTR-005 (IMessageChannel), [ADR-COMM-001](../../DECISIONS.md) (Dict at Boundary)

## ADR-RTR-009: FrameShm — одна стратегия записи + кэш handles + громкий pickle-fallback (Ф7 G.3)

**Статус:** принято
**Дата:** 2026-07-14
**Refs:** [plans/2026-07-06_constructor-master/plan.md](../../../plans/2026-07-06_constructor-master/plan.md) (Ф7 G.3 a/d), [frame-pool-idea.md](../../../plans/2026-07-06_constructor-master/frame-pool-idea.md) (спутники: кэш handles), ADR-COMM-003 (слияние двух реализаций), [ADR-SRM-011](../shared_resources_module/DECISIONS.md) (формат слота/seqlock)

**Контекст.** `FrameShmMiddleware` после ADR-COMM-003 — один класс, но с ДВУМЯ путями записи
кадра в SHM:
- `strip_and_write` (generic data-pipeline, КАНОН): lazy-alloc + realloc-on-grow, round-robin
  `_write_index % _coll`; живой путь камеры (`generic_process.py` → `strip_data_frame_on_send`).
- `on_send` (wire/frontend): `find_free_index` + `write_images`, БЕЗ lazy-alloc. `find_free_index`
  всегда возвращает 0 (`index_usage` никем не инкрементится — де-факто одно-слотовый), т.е.
  вторая стратегия выбирала слот сломанным механизмом и полагалась на внешнюю пред-аллокацию.

**Решение (a) — одно ядро записи, канон = generic.** Выделен приватный `_write_frame_into_slot(frame)
→ dict | None` (lazy-alloc + realloc-on-grow + round-robin + `write_images`, возвращает
координаты слота или None при неудаче). Оба публичных пути делегируют в него, различаясь ТОЛЬКО
адаптером: `strip_and_write` берёт frame из item-dict и кладёт координаты туда же; `on_send`
берёт `msg["frame"]` и кладёт координаты в `msg["data"]` (+ back-compat `width`/`height`).
`find_free_index`-выбор слота из send-пути снят (сломанный, всегда 0). Round-robin — тот же
слот-механизм, что теперь под seqlock (ADR-SRM-011): перезапись слота под читателем безопасна
(reader дропает по generation).

**Решение — кэш SHM-handles читателя, флаг `FW_SHM_HANDLE_CACHE` (дефолт False).** Основной
cross-process путь `_read_shm_from_actual_name` открывал `SharedMemory(name=...)` и закрывал
на КАЖДЫЙ кадр (open/mmap/close + resource_tracker — десятки µs, «спутник №1» frame-pool-idea).
При включении — инстанс-кэш `shm_actual_name → SharedMemory` с LRU-кэпом (8); инвалидация по
смене имени (grow-realloc/incarnation меняют имя → новая запись, старая вытесняется + close);
teardown закрывает все. Дефолт False = прежний open/close на кадр.

**Решение (d) — громкий pickle-fallback (перф-ревью п.3).** При неудаче SHM-write кадр молча
оставался в сообщении и уезжал pickle-через-Queue (латентность ×3, метрик ноль). Добавлен
plain-int `frame_pickle_fallbacks` (по образцу `frame_boundary_crossings`, БЕЗ lock/колбэка на
hot-path — ревью G.6 F5) + throttled WARNING через `log_error` (фасад ErrorManager). Счётчик
агрегируется в `RouterManager.get_stats()` (`introspect.router_stats`) на ЧТЕНИИ → heartbeat →
state-дерево → вкладка Pipeline; поле state = сигнал для будущего alerting NEW-7 (В5). Всегда-on
(чистая наблюдаемость, не смена поведения — прецедент G.6).

**Альтернативы (отвергнуты).** *Удалить on_send/on_receive целиком* — отвергнут: wire.configure
и frontend-приём живут на них; унифицируется ЯДРО записи, а не входные адаптеры. *Счётчик
fallback с колбэком в router* — отвергнут (reference-cycle + lock на send, урок G.6 F5).

**Последствия.** Одно ядро записи (проще seqlock-интеграция: begin/end поколения в одном месте).
Кэш handles снимает основной syscall-налог cross-process (замер — G.5/soak). Тихий slow-path
исчез: pickle-fallback виден в state. Три пути (`strip_and_write`/`on_send`/`restore_frame`) под
общим seqlock- и handle-cache-контрактом. Флаги дефолт-OFF, откат = флаг off.

## ADR-RTR-010: release-on-evict — возврат SHM-займа при вытеснении кадра из полной очереди

**Статус:** accepted (2026-07-21, ветка fix/bug-hunt-live-findings)

**Контекст.** Под loan-протоколом (Ф7 G.5+) writer занимает слот кольца с
`refcount=num_consumers`; release шлёт дочитавший потребитель. Но
`QueueRegistry.remove_old_if_full` (drop_oldest) вытесняет кадр из полной data-очереди ДО
прочтения — потребитель его не увидит, release не пришлёт. `reclaim_reader` покрывает только
МЁРТВОГО читателя. Итог (воспроизведено live 2026-07-21, webcam_sketch + 9 флагов лесенки):
≥ring_depth вытеснений на старте (lines грузит TEED ~10 с) → free-list owner'а исчерпан
навсегда, конвейер заморожен, skipped растёт со скоростью FPS. Это открытая fault-инъекция
G.7 «2.4 slow-consumer», пойманная первым живым запуском
(docs/audits/2026-07-20_bug-hunt.md §9, LIVE-2).

**Решение.** Вытесняющая сторона (транспорт) отпускает займ вытесненного кадра, доставляя
владельцу `shm_release(evicted=True)`:

- `QueueRegistry.send_to_queue` получает опциональный колбэк `on_evict(item, process)` —
  чистый Callable, слой памяти о кадрах НЕ знает (границы слоёв целы).
- `RouterManager` регистрирует хук под гейтом `_frame_loan_active` (пересчёт при
  (un)register_frame_middleware); при flags-off хук не навешивается вовсе — поведение
  бит-в-бит прежнее.
- `_on_frame_evicted` шлёт владельцу `shm_release` через **system-почту**, а не прямым
  вызовом: release обязан исполняться на треде message_processor владельца
  (single-thread-release инвариант пула), а вытеснение идёт на треде-писателе.
  owner==self → почта в свою же system-очередь; owner≠sender (fan-in) → IPC владельцу.
- `LoanLedger.release_evicted` — release БЕЗ generation-guard: тикет вытеснения поколения
  не несёт (сообщение никем не читалось), а пока refcount>0 слот не переиспользуется, так
  что «прошлого займа» быть не может. refcount>0-guard и dedup-по-reader сохранены.
  Отдельный счётчик `slots_released_on_evict` → `frame_loans_released_on_evict` в
  `RouterManager.get_stats()` — потеря видима; рост в steady-state = устойчивая перегрузка
  приёмника (чинить пропускную способность, не release-контур).

**Альтернативы (отвергнуты).**
*Owner-side TTL-reclaim* — требует периодического тика на треде message_processor (нет
инфраструктуры), тюнинг TTL, риск ложного реклейма живого slow-consumer; ленивый GC вместо
немедленного точечного release. *Прямой `release_slots` из send-треда* — гонка со штатным
release за lock-free refcount пула.

**Последствия.** Перманентная смерть кольца при перегрузке приёмника устранена; страховкой
остаётся В1 post-use re-check (занижение refcount безопасно — drift → drop, не порча,
§8.2 G.5). Потеря почты release покрыта reclaim соседа + В1.

**Reversible:** yes (flags-off = прежнее поведение).
**Refs:** docs/audits/2026-07-20_bug-hunt.md §9 LIVE-2.

## ADR-RTR-011: контракт `request()` исполняется, а не документируется; `request_async` — путь для приёмного потока

**Статус:** accepted (2026-08-23, ветка feat/observation-port)

**Контекст.** В докстринге `RouterManager.request()` с самого начала стояло: «нельзя
вызывать из того же потока, который крутит `receive()`/`start_listening` — ответ некому
будет разобрать (дедлок до таймаута)». Проверки в теле метода не было, и нарушение выглядело
как обычный таймаут: `pending.event.wait(timeout)` блокировал безусловно и возвращал
`{"success": False, "error": "timeout"}`. Два живых нарушителя, оба найдены замером
2026-08-23, а не чтением:

1. `StateProxy._resync()` — вызов с приёмного потока, 5 с простоя всей системной почты
   процесса на каждый разрыв revision (детали и числа — ADR-SS-022);
2. `subscribe(sync=True)` из `start()` плагина — шаг 6 `ProcessModule.initialize()` идёт ДО
   создания `message_processor` (шаг 7), поэтому ответ разобрать некому В ПРИНЦИПЕ. Замер:
   старт `telemetry_sink` простаивал 10.03 с = два таймаута; четыре стартовые подписки
   GUI-процесса (`processes.**`/`system.**`/`devices.**`/`calibration.**`) — 20.03 с, и все
   четыре всё равно оставались неподтверждёнными (`_confirmed_patterns` = 0).

**Решение.** Роутер знает свои приёмные потоки и обязан этим пользоваться.

- `_recv_local.depth` — счётчик входа в `receive()` для ТЕКУЩЕГО потока (не флаг: вложенный
  вызов не имеет права снять чужую отметку; снимается в `finally`, иначе исключение из
  `receive()` навсегда «отравляет» поток).
- `depth > 0` при вызове `request()` → `RouterReentrantRequestError`. Исключение, а не dict
  с кодом: нарушает контракт ВЫЗЫВАЮЩИЙ КОД, а починить его можно только зная место вызова —
  traceback показывает, поле `error` не показывает никогда. Сообщение при этом НЕ
  отправляется: иначе ответ приехал бы в пустой pending-слот и лёг «опоздавшей почтой»
  (ровно то, что наблюдалось раз в 5.06 с).
- `_pump_seen` — «приёмный цикл на этом роутере хоть раз крутился», взводится в `receive()` и
  не гаснет. Если не взведён, `request()` ждёт появления приёмника не дольше
  `_NO_PUMP_GRACE_SEC = 0.5` и возвращает `{"error": "timeout", "reason": "no_receive_pump"}`.
  Отказ мягче реентрантного: сообщение УХОДИТ (fire-and-forget-деградация — команда доедет и
  исполнится, мы лишь не узнаем результата), а `error` намеренно остался `timeout`, чтобы не
  ломать разбор ошибки у существующих вызывающих; причина названа отдельным полем и WARNING'ом.
- `request_async(message, on_response=..., timeout=...)` — законный путь для приёмного потока:
  pending-слот держит колбэк вместо события, приёмный цикл зовёт его сам. Колбэк вызывается
  РОВНО ОДИН РАЗ (ответ / таймаут / провал отправки), и держит это не соглашение, а арбитраж:
  обе дороги снимают слот через `_take_pending` под `_pending_lock`, зовёт колбэк только тот,
  кому слот достался. Просроченные слоты подметает `_expire_async_pending` на приёмном такте,
  под guard'ом `_async_pending_count` (пока асинхронных запросов нет — нулевая работа).

**Почему окно 0.5 с, а не 0.** Вызвавший поток мог опередить создание `message_processor` на
доли секунды — тогда ждать ответ законно. Цена ошибки в БОЛЬШУЮ сторону — простой на старте
(то, что чинится), в МЕНЬШУЮ — ложный отказ живому запросу. Приёмный цикл поднимается шагом 7
`initialize()` сразу за плагинами, тики цикла 10 мс: запас два порядка.

**Альтернативы (отвергнуты).** *Оставить контракт комментарием, починив только вызывающих* —
отвергнут: следующий вызывающий повторит ошибку, и она снова будет выглядеть таймаутом связи.
*Возвращать dict вместо исключения на реентрантном вызове* — отвергнут: без traceback место
вызова неизвестно, а именно оно и есть дефект. *Флаг-опт-аут `allow_from_receive_thread`* —
отвергнут как преждевременный: легитимного вызывающего с приёмного потока в дереве нет
(ответ физически некому разобрать — вся почта-ответы едет системной очередью, которую
дренирует тот же поток); появится — получит громкое исключение с местом вызова.

**Последствия.** Реентрантный вызов отказывает за < 0.001 с вместо 5.000 с (приёмочный C3).
Подписка без приёмника — 0.5 с вместо 5 с на вызов (C4). Обычные потоки не задеты: 8 потоков
× 5 запросов под работающим приёмным циклом — ни одного отказа
(`test_contract_refusal_does_not_fire_on_normal_threads_under_load`), C5 (пара-контроль) зелён.
`test_request_timeout_returns_error_and_cleans_pending` остался зелёным без правок — ровно
потому, что `error` сохранил значение `timeout`.

**Reversible:** yes (снять проверку в `_assert_not_receive_thread` — но тогда обязателен и
откат ADR-SS-022, см. предупреждение там).
**Refs:** ADR-SS-022, `tests/test_request_contract_guard.py`,
`state_store_module/tests/test_resync_starvation_acceptance.py` (C3/C4/C5).

## ADR-RTR-012: SocketChannel без head-of-line — обработчик в daemon-потоке под потолком на соединение; потолок строки на обоих read-loop

**Статус:** accepted (2026-09-24, ветка feat/gui-service-1.3a, Task 1.3a плана gui-service)

**Контекст.** `SocketChannel._read_loop` звал `on_inbound(msg)` инлайн в read-потоке
соединения. `SocketBridgeAdapter.on_inbound` внутри делает `router.request(timeout=…)`, то
есть медленная команда держала ВСЕ следующие строки того же соединения — head-of-line.
Пока дверь обслуживала один `backend_ctl` на запрос, это было незаметно; Пульт Task 1.2
ходит одним мультиплексным соединением, и медленная команда там останавливает весь GUI.
Приёмка тестера (`test_socket_channel_hol_acceptance.py`) до правки: быстрый ответ за
медленным на ТОМ ЖЕ соединении не пришёл за 0.5 с (elapsed 0.508 с). Второй дефект того же
места: оба read-loop (сервер и `SocketClient`) копили `buf` без ограничения — строка без
`\n` растила память неограниченно.

**Решение.**

1. **Разбор и привязка сессии остаются синхронными в read-потоке**, в поток уходит только
   вызов `on_inbound`. `_bind_session` обязан отработать ДО передачи сообщения: ответ
   обработчика адресуется по уже установленной привязке (D.1), а разрыв соединения снимает её
   через единственную точку `_drop_clients` — `on_session_closed` звучит ровно один раз.
2. **Один daemon-`threading.Thread` на сообщение** под `threading.BoundedSemaphore` на
   соединение, `_MAX_INFLIGHT_PER_CONNECTION = 8`. Сверх потолка read-loop ждёт слот
   (`acquire(timeout=0.1)` в цикле с проверкой `_running`) — backpressure на сокет, TCP-окно
   отдаёт её клиенту; `close()` не упирается в поток на полном семафоре. Слот возвращается в
   `finally` обработчика. Порядок ответов не нужен: клиент сопоставляет их по `request_id`.
3. **Потолок строки** `max_line_bytes`: `SocketChannel` — 1_048_576, `SocketClient` —
   16_777_216 (ответы state-поддерева/истории крупнее запросов). Нет `\n`, а буфер уже больше
   потолка → режим сброса до ближайшего `\n`, байты не копятся (буфер ≤ потолок + recv-чанк
   4096); целая строка длиннее потолка отбрасывается тем же путём. WARNING — один на строку,
   соединение живо. На клиенте `request()`, чей ответ отброшен, заканчивается своим
   таймаутом — соединение потерянным НЕ объявляется.
4. **Путь записи не тронут:** общий `_write_lock` и таймаут клиентского сокета 0.5 с
   (тотальный таймаут `sendall`). Медленный читатель отбрасывается не позже чем через ~0.5 с
   (замер тестера: 0.505 с). Уточнено дополнением 2: запись стоит не дольше одного
   таймаута сокета на медленного клиента. Посокетные локи не заведены (YAGNI).

**Почему daemon-потоки, а не `ThreadPoolExecutor`.** Воркеры executor'а не-daemon: выход
интерпретатора ждёт их, и обработчик, застрявший в `router.request(timeout=60)`, задерживал
бы стоп процесса на минуту — ровно то, что чинит работа lifecycle-stop-ownership в main.
Потолок 8 на соединение делает число потоков ограниченным без пула.

**Альтернативы (отвергнуты).**
- *Один воркер-поток на соединение с очередью* — отвергнут: развязывает read-поток с
  обработкой, но строки одного соединения по-прежнему идут последовательно, то есть HOL
  на единственном мультиплексном соединении Пульта (Task 1.2) остаётся ровно тем же.
- *`ThreadPoolExecutor`* — см. выше (не-daemon воркеры держат выход процесса).
- *Посокетные локи на запись* — не нужны при измеренных 0.5 с худшего случая.

**Последствия.** Приёмка тестера 9/9 зелёная (3 файла); авторские hazard-тесты
`tests/test_socket_channel_hol_hazards.py` (обработчик переживает соединение — записи нет;
`close()` при полном семафоре < 1 с и read-поток выходит; 9-й запрос ждёт, соседнее
соединение отвечает < 0.5 с; oversize 2 МиБ чанками — пик аллокаций < 256 КиБ; конкурентный
`_drop_clients` — `on_session_closed` один раз). Смежное в `backend_ctl`: `EventHub`
получил `max_bytes_per_ring` (16 МиБ на кольцо) с вытеснением тем же видимым путём, что
по maxlen.

**Дополнение (2026-09-24, находки инъекций лида).**

- *Инвариант порядка: «сессия закрыта ПОСЛЕ последнего обработчика этой сессии».* Пока
  обработчики шли в read-потоке, `on_session_closed` (→ `_forget_closed_session` →
  `broker.forget_session`) звучал строго после них, включая наблюдателя `on_request`
  (`_note_point_request` → `broker.note_point`). После выноса в потоки обработчик мог
  оставаться в работе, когда read-loop уже вышел: `note_point` после `forget_session` —
  призрачное намерение подписки мёртвой сессии (класс Н3-1). Воспроизведено до правки:
  `test_session_closed_fires_after_last_handler_of_the_session` — `['closed:s7']` при живом
  обработчике. Правка: на выходе read-loop соединение СРАЗУ снимается с учёта
  (`_unregister_clients` — ответы ему дальше «session not connected», без записи), затем
  read-поток забирает все `_MAX_INFLIGHT_PER_CONNECTION` слотов (тот же опрос), и только
  потом `_finish_drop` зовёт `on_session_closed` и закрывает сокет. `_drop_clients` разрезан
  на две половины; каждая сессия попадает ровно в один вызов снятия — оповещение ровно одно.
- *Почему без дедлайна.* Обработчик ограничен таймаутом своего запроса — ровно тем же, чем
  был ограничен read-поток, пока звал его инлайн. Ждёт только daemon-поток мёртвого
  соединения; при `close()` канала (`_running` = False) ожидание сдаётся сразу, остановка
  не висит (`test_close_with_full_semaphore_returns_and_read_thread_exits`).
- *J5: «привязка до передачи» не имела теста.* Отложенный на 50 мс `_bind_session` оставлял
  все 49 тестов зелёными. Добавлен `test_session_bound_before_handler_on_first_line`: первая
  строка соединения несёт session, обработчик сразу отвечает адресно — под J5 красный.
- Счётчики `SocketBridgeAdapter` (`_lost_responses`, `_observer_errors`) теперь пишутся из
  нескольких потоков — под одним `threading.Lock` (инкремент и чтение в `get_stats`).

**Дополнение 2 (2026-09-25, ревью 1.3a, итерация 1).**

- *Инвариант порядка держится на КАЖДОМ пути снятия.* Дополнение 1 закрыло только выход
  read-loop; путь сбоя записи (`send`/`_send_to_session` → `_drop_clients`) — тот самый,
  которым отбрасывается медленный читатель, — звал `on_session_closed` сразу. Пробник
  ревьюера: `closed:s1 0.704` раньше `handler_done 1.501`; брокер (`observability_broker.py:290`)
  отвергает поздний `note_point` → отписка не доходит до дочернего → призрачный форвардер
  (класс Н3-1). Правка: сбой записи под `_write_lock` только **помечает** сокет (`_dead`) и
  делает `shutdown(SHUT_RDWR)`; ничего не снимает и не оповещает. `shutdown` будит recv
  read-loop'а (EOF), и соединение снимает единственная точка — выход read-loop
  (`_unregister_clients` → `_await_handlers` → `_finish_drop`). `_drop_clients` удалён.
- *Запись стоит не дольше одного таймаута сокета (0.5 с) на медленного клиента.* Прежний
  текст «остальные ждут ≤ 0.5 с, один раз» был неверен: второй отправитель, взявший снимок
  до снятия, садился на тот же сокет ещё на 0.5 с (ревьюер: 1011.6 / 997.2 мс, два
  `timed out` через 0.501 с) или писал в закрытый (`[Errno 9] Bad file descriptor`, 7 на
  отброс). Теперь помеченный или закрытый (`fileno() == -1`) сокет отправитель пропускает
  под тем же `_write_lock`; `_finish_drop` закрывает сокеты тоже под ним. Замер после
  правки (3 отправителя × 30 push по 256 КиБ, застрявший A + читающий B, 3 прогона):
  max `send()` 503.7 / 504.7 / 504.6 мс, WARNING — 1, EBADF — 0, A снят; до правки на том
  же сценарии — max 503.7 мс, но 3 WARNING, из них 2 EBADF (секундный простой ревьюера
  этим сценарием не воспроизвёлся).
- Тесты: `test_session_closed_after_handler_on_write_failure_path` (до правки
  `['closed:s8']` при живом обработчике), `test_second_sender_to_stuck_socket_does_not_wait_again`
  (до правки — EBADF в WARNING). Счётчики `_rx`/`_tx` — под `_stats_lock`.

**Reversible:** yes (вернуть инлайн-вызов в `_handle_line`; kwargs потолков — с дефолтами).
**Refs:** plans/2026-09-22_gui-service/phase-1-one-machine.md (Task 1.3a), ADR-RTR-008,
`tests/test_socket_channel_hol_acceptance.py`, `tests/test_socket_client_max_line_acceptance.py`.
