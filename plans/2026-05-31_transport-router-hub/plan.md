# Plan: Транспортный хаб — RouterManager как единая точка + каналы по содержимому (master)

- **Slug:** `transport-router-hub`
- **Дата:** 2026-05-31
- **Статус:** IN PROGRESS. **P0 ✅ + P1 ✅ + P2 ✅** (ветка `refactor/transport-router-hub`): P0.1 recon (`f212d1d2`), P0.2 контракт (`4e22426e`), P0.3 ADR (`c8e68832`), P1 хаб на отправке (`2f417169`+`9dd31d73`), P2 иерархическая адресация (`09cd95a6` P2.1 + `<hash>` P2.2/P2.3, **решение ГИБРИД: кадры—трубы, команды—почта**, smoke end-to-end: дисплей кажет кадры, 0 ERROR). **P3 каналы по kind ⏳ next.** P4–P5 — манифест.
- **Ветка:** `refactor/transport-router-hub` (создаётся при старте P0; НЕ автоматически).
- **Источник анализа:** [`multiprocess_framework/docs/COMMUNICATION_MAP.md`](../../multiprocess_framework/docs/COMMUNICATION_MAP.md) + `COMMUNICATION_MAP_raw.json` (аудит 23 подсистем, 166 механизмов, 2026-05-31).
- **Смежные планы:** [`constructor-maturity`](../2026-05-29_constructor-maturity/plan.md) — P1 (движок команд/ActionBus) и P6 (вынос в framework). Этот план НЕ дублирует P1; ActionBus-удаление остаётся за constructor-maturity. [`processes-workers-runtime-debts`](../../multiprocess_prototype/plans/processes-workers-runtime-debts.md) — Фаза 2 `assigned_worker` (см. §«Связь с assigned_worker»).

---

## Назначение

Замысел владельца (изначальный, подтверждён 2026-05-31): **RouterManager — единая «входная дверь»** (интермодальный хаб, как Франкфурт/Хунцяо). Компонент формирует `Message` (билет: что за груз + куда), отдаёт его в Router, а Router по содержимому билета сам выбирает **канал** и доставляет. Сообщение самоописательно — **всё зависит от сообщения**.

Аудит показал, что шину спроектировали верно (Router в каждом процессе), но **достроили наполовину**: сегодня ~80–90% сообщений и ~99% байт идут **в обход** Router (`send_message → queue_registry`, прямой SHM, `EventManager` dual-write), а channel-routing почти мёртв. Отсюда 6+ способов отправки и «невозможно поддерживать».

**Цель плана:** довести шину до изначального замысла — **один способ отправки `router.send(message)`**, Router маршрутизирует по `kind` в канал и по иерархическому `address` на уровень. Каналы становятся **живыми** (по одному на тип груза), обходы и мёртвый код удаляются. Без костылей.

> **Этот план ОТМЕНЯЕТ §5.1 `COMMUNICATION_MAP.md»** («оставить process-name+queue, каналы депрекейтить» — это была минимальная «асфальтировать тропу»). Владелец выбрал противоположное направление: **построить хаб правильно**. Обоснование, почему это НЕ больше звеньев: целевой путь `router.send → Channel → queue` имеет ту же глубину, что сегодняшний `send_message → send_to_process → queue`, но это **один** вход и **одна** реализация вместо трёх дублей. Находки §3 (мёртвый код) и §5.2 (слияния дублей) аудита остаются в силе и используются здесь как материал.

---

## Что УЖЕ есть во фреймворке (переиспользуем, НЕ изобретаем)

Чтение README модулей (2026-05-31) показало: **хаб уже спроектирован и частично построен** — его на уровне IPC обходят. План = ДОСТРОИТЬ и подключить существующее, не вводить параллельные сущности.

| Замысел владельца | Уже реализовано (символ) | Статус |
|---|---|---|
| «Телефонная станция» (читает билет → канал) | `ChannelRoutingManager` (CRM): `ChannelRegistry` + `Dispatcher` + `register_route(key→channel)` + `route(data, key_field)` | ✅ есть, база для Router/Logger/Error |
| Хаб = единая точка | `RouterManager(CRM)`: `send(msg) → middleware → _resolve_channels → IMessageChannel.send`; `receive() → message_dispatcher → handler` | ✅ есть, но **обходится** |
| Каналы (тупые трубы) | `IChannel → IMessageChannel/ILogChannel`; `MessageChannel`, `QueueChannel`; кастомные by-design (`SocketChannel`/`DbChannel`) | ✅ контракт есть; нужны Frame/Event как `IMessageChannel` |
| «Что за груз» (kind) | `Message.type` = `MessageType` (COMMAND/DATA/EVENT/STATE/LOG/…) | ✅ есть — **НЕ вводить новый `kind`** |
| Билет | `Message(SchemaBase)` + `MessageAdapter` (`.command/.data/.event/.log/...`) | ✅ есть — **НЕ вводить новый конверт** |
| Claim Check для кадров | `MessageType.DATA` + поля `use_shared_memory` + `memory_key` | ✅ есть by-design |
| Таблица kind→канал | `register_route(key, channel_name)` + `channel_dispatcher` (exact/pattern/broadcast) | ✅ механизм есть; на отправке **не задействован** (route-by-pattern dormant) |
| Логи/ошибки — тоже каналы станции | `LoggerManager`/`ErrorManager` наследуют CRM; `ILogChannel(IChannel)` в общем `ChannelRegistry` | ✅ уже единая иерархия |
| Per-worker адресация | `RouterAdapter.send_to_channel("process_2_worker_in", ...)`; Roadmap router_module | 🟡 предвидено, не формализовано → P2 |
| Результат команды (анти fire-and-forget) | `correlation_id`/request-response | 🟡 Roadmap «Высокий» → учесть в P4 |
| Config-driven каналы | объявление каналов в конфиге процесса | 🟡 Roadmap «Высокий» → P1/P3 |

**Что РЕАЛЬНО новое (а не переоткрытие):** (1) подключить реальные IPC-очереди `queue_registry` как `IMessageChannel` и заставить `send` резолвить канал из `targets`+`type` (сегодня `send_message` зовёт `queue_registry` напрямую, мимо роутера); (2) иерархическая адресация в `targets`; (3) `FrameChannel`/`EventChannel`/`StateChannel` как first-class каналы; (4) миграция вызовов на `router.send`; (5) `correlation_id`.

> **Развязка `queue_registry` ↔ ChannelRegistry (ключевое решение):** каналы делаем
> **address-aware по qtype**, а не один-канал-на-получателя. Т.е. 2–4 канала на процесс
> (`SystemChannel`/`DataChannel`(+SHM)/`EventChannel`/`StateChannel`); канал читает адрес из
> `msg.targets` и кладёт в нужную очередь `queue_registry` по `address[0]`. `queue_registry`
> остаётся нижним хранилищем очередей, спрятанным ЗА каналом. Это не плодит каналы при
> иерархии и совпадает с семантикой нынешнего `_deliver_by_targets`, только внутри канала.

---

## Целевая архитектура

> Ниже — концепция в терминах владельца; в скобках — реальные символы фреймворка (реализуем поверх них).

### Три понятия (и больше ничего)

```
                       ┌──────────────── RouterManager (хаб, в каждом процессе) ───────────────┐
 компонент             │  SEND (Router):                                                        │
 строит Message  ──────▶│   читает message.kind → выбирает ОДИН Channel                          │──▶ транспорт
 router.send(msg)      │   читает message.address → доставляет на нужный уровень (prefix)         │   (queue/SHM/fanout)
                       │                                                                          │
 handler(msg) ◀────────│  RECEIVE (Dispatcher):                                                  │◀── poll каналов
                       │   poll() всех каналов → message_dispatcher → handler по kind/command     │
                       └──────────────────────────────────────────────────────────────────────────┘
```

1. **Message** (билет) — существующий `Message(SchemaBase)`/`MessageAdapter`, Dict-at-Boundary (правило #1). НЕ новый конверт. Используем существующие поля:
   ```
   {
     "type":    MessageType,   # COMMAND|DATA|EVENT|STATE|LOG|... — это и есть «kind» (НЕ вводим новое поле)
     "targets": ["proc"] | ["proc.worker"] | ["proc.worker.…"],  # иерархия dotted-строкой В существующем targets:list[str]
     "command": "...",         # для COMMAND — какой handler
     "data":    {...},         # payload
     "use_shared_memory": true, "memory_key": "...",  # для DATA-кадров — Claim Check (поля уже есть в MessageType.DATA)
     "sender":  "...",
     "id":      "..."          # = correlation_id (request/response, уже есть)
   }
   ```
   Иерархия адреса живёт ВНУТРИ каждого `targets`-элемента как dotted-путь `process[.worker[.…]]` (prefix: процесс обязателен первым). Это переиспользует `targets:list[str]` (мультикаст сохранён) и согласуется с `RouterAdapter.send_to_channel("process_2_worker_in")`.
2. **Channel** — существующий `IMessageChannel(IChannel)` из `channel_routing_module` (НЕ новый Protocol). База `MessageChannel`, готовый `QueueChannel`; новые каналы — подклассы (как by-design `SocketChannel`/`DbChannel`). **Address-aware по qtype** (см. развязку выше):
   | Канал | type (kind) | транспорт |
   |---|---|---|
   | `SystemChannel`/`QueueChannel('{addr}_system')` | COMMAND, SYSTEM | system-очередь `queue_registry` по `targets` |
   | `DataChannel`/`QueueChannel('{addr}_data')` | DATA | data-очередь; кадры — SHM (Claim Check) |
   | `FrameShmMiddleware` (один, framework) | — | strip_and_write/restore внутри DataChannel |
   | `EventChannel` | EVENT | fan-out (cross-process pub/sub) |
   | `StateChannel` | STATE | `state.changed` дельты (`DeltaDispatcher`) |
   | `ILogChannel` (FileChannel/ConsoleChannel) | LOG/ERROR | уже в общем `ChannelRegistry` (logger/error менеджеры) |
3. **Handler** — функция-получатель в **одном** диспетчере (`message_dispatcher` через `register_message_handler`). `command_module/CommandManager` — реестр прикладных команд, который зовёт диспетчер (а НЕ второй роутер; убрать двойную диспетчеризацию — P4.4).

Маршрутизация на отправке = существующий `_resolve_channels`/`channel_dispatcher` + `register_route(MessageType→channel)`. То есть «таблица kind→канал» — это `register_route`, уже встроенный механизм, сейчас на отправке dormant.

### Иерархическая адресация (см. memory `project-hierarchical-addressing`)

- `address` — упорядоченный список: `[process, worker, ...]`. Почтовый принцип: Страна→Город→…→Человек.
- Указать только процесс — можно. Воркер без процесса — нельзя (prefix обязателен).
- Нижние уровни опциональны → **prefix-routing**: доставляем на самый глубокий заданный уровень.
- **Cross-process** доставка — в очередь процесса (`address[0]`). **Воркер и глубже** (`address[1:]`) резолвятся **внутри** процесса-получателя его Router/диспетчером (маршрут на воркер/in-process очередь), **не** плодя IPC-очереди. Это «меньше звеньев» и стыкуется с in-process handoff из плана `assigned_worker`.
- Оси ортогональны: **`address` = куда (иерархия)**, **`kind` = что за груз (канал)**. Обе живут в билете. Не путать с прежним «Router-каналом» (`ROUTING_GLOSSARY.md`).

### Claim Check для кадров

Пиксели (numpy) НЕ едут по шине: `FrameChannel` пишет кадр в SHM, по очереди отправляет только `shm_ref` ({shm_name, index, w, h}). Получатель восстанавливает. Нулевая копия, нулевой регресс перфа. Узаконенный намеренный «bypass» внутри канала.

---

## Принципы

1. **No big-bang / strangler.** Прототип остаётся запускаемым после каждой фазы. Новый путь вводится рядом, старый делается тонким адаптером, удаляется в конце.
2. **No crutches.** Никаких временных обёрток, остающихся в проде. Каждый шаг либо доводится до конца, либо не начинается.
3. **Fewer links.** Любое изменение обязано не увеличивать число звеньев живого пути (acceptance-критерий в задачах).
4. **Один вход / один диспетчер / тупые каналы.** Не вкладывать command manager в каналы; не плодить диспетчеры.
5. **Dict-at-Boundary** сохраняется: между процессами — dict-билет; Pydantic — внутри процесса.
6. **Investigation-first.** Память устаревает — перед каждой фазой `qex`/`grep`/`serena` актуализируют call-sites (P0.1 — обязателен первым).
7. **Слои.** Хаб и каналы живут во `framework`; прототип только формирует билеты (`framework → Services → Plugins → prototype`).
8. **Удаление — только после обсуждения.** Ни один модуль/символ не удаляется автоматически; дефолт — изоляция, не `rm` (см. P5).
9. **Reuse-first.** Контракты хаба УЖЕ есть во фреймворке (CRM, `IMessageChannel`, `MessageType`, `register_route`) — мы их ДОСТРАИВАЕМ и подключаем, а не вводим новые сущности.

---

## Источники истины

| Документ/символ | Что |
|---|---|
| `COMMUNICATION_MAP.md` §1–§3 | инвентарь цепочек, роль Router, мёртвый код, дубли |
| `COMMUNICATION_MAP_raw.json` | сырые карты 23 подсистем + точные call-sites обходов (router_audit.bypasses) |
| `router_module/core/router_manager.py` | `send`/`receive`/`_resolve_channels`/`_deliver_by_targets`/`register_message_handler` |
| `shared_resources_module/queues/core/manager.py` | `queue_registry.send_to_queue`/`broadcast_message` |
| `process_module/communication/process_communication.py` | `send_to_process`/`send_message`/`broadcast` (главный обход) |
| `process_module/generic/{source_producer,pipeline_executor,data_receiver,frame_shm_middleware}.py` | data-plane |
| `router_module/middleware/frame_shm_middleware.py` | второй FrameShmMiddleware (слияние, §5.2) |
| `state_store_module/manager/delta_dispatcher.py` | StateChannel (уже U1) |
| `dispatch_module/core` + `command_module/core` | message_dispatcher + CommandManager (двойная диспетчеризация §3.5) |
| `shared_resources_module/events/core/manager.py` | EventManager dual-write (EventChannel) |
| memory `project-hierarchical-addressing`, `command_engine_audit`, `processes-workers-runtime-feature` | требования владельца |

> **Правило:** перед каждой задачей P*.x — `qex`/`grep` актуальных call-sites (память устаревает).

---

## Декомпозиция

```
P0 контракт+ADR (investigation-first) ─▶ P1 хаб на отправке (strangler) ─▶ P2 иерархическая адресация + воркер
        │                                                                          │
        └────────────────────────────────────────────────────────────────────────┘
P3 каналы по kind (Frame/State/Event) ─▶ P4 миграция отправителей + удаление обходов/дублей ─▶ P5 dead-code + вынос в framework + инварианты
```

Рекомендуемый порядок относительно других веток — см. §«Связь с assigned_worker» и §«Сиквенс».

---

## P0 — Контракт и ADR (фундамент, без смены поведения)

**Цель фазы:** зафиксировать билет (Message v2), контракт Channel, таблицу `kind→channel`, иерархию адреса и ADR — до единой строки исполнения. Актуализировать call-sites.

### Task P0.1 — Investigation: актуализировать карту обходов (read-only)
**Level:** Senior+ (Opus) · **Assignee:** investigator/teamlead
**Goal:** Подтвердить/обновить список call-sites обхода Router и форму dict-билета на текущем коде (память аудита от 2026-05-31 могла устареть после правок Фазы 1 assigned_worker).
**Files:** read-only; вывод — `plans/2026-05-31_transport-router-hub/recon.md`.
**Steps:**
1. По `COMMUNICATION_MAP_raw.json.router_audit.bypasses` пройти каждый call-site (`send_to_process`, `broadcast_message`, `_deliver_by_targets`, `SourceProducer._send_item`, `PipelineExecutor`, `ProcessHeartbeat`, `QueueRegistry.broadcast_message`, прямой SHM) — `serena find_referencing_symbols`/`qex` подтвердить, что путь жив и сигнатуры те же.
2. Зафиксировать фактические ключи dict-сообщений на каждом живом пути (`type`/`channel`/`targets`/`data`/`queue_type`/`command`).
3. Список «уже мёртвых» из §3.4 перепроверить (codegraph callers = 0) — что можно удалять в P5 без миграции.
4. Записать `recon.md`: таблица call-site → kind → нужный канал → объём миграции.
**Acceptance:** - [ ] recon.md покрывает все bypass из raw.json - [ ] для каждого — kind + целевой канал + статус (мигрировать/удалить) - [ ] расхождения с аудитом отмечены.
**Out of scope:** любые правки кода.

### Task P0.2 — Контракт: иерархический адрес + address-aware каналы + routing table (на существующих символах)
**Level:** Senior+ (Opus) · **Assignee:** teamlead · **module-contract: lite (расширение существующих)**
**Goal:** Зафиксировать иерархию адреса в существующем `Message.targets`, контракт address-aware канала поверх существующего `IMessageChannel`, и таблицу `MessageType→channel` через существующий `register_route` — без новых сущностей и без проводки в рантайм.
**Files:**
- `multiprocess_framework/modules/message_module/` — хелперы парсинга/валидации dotted-адреса в `targets` (`"proc.worker"` → `["proc","worker"]`, prefix: процесс обязателен). **Не добавлять `kind`/`address`** — используем `type`/`targets`. README-врезка.
- `multiprocess_framework/modules/router_module/` — спека address-aware канала (подкласс `MessageChannel`, читает адрес из `msg["targets"]`); таблица `MESSAGE_TYPE_TO_CHANNEL` поверх `register_route`. БЕЗ нового Protocol — переиспользуем `IMessageChannel`.
- contract-тесты в существующих `message_module/tests`, `router_module/tests`.
**Steps:**
1. Хелпер адреса: parse/validate dotted `targets`-элемента (`process[.worker[.…]]`), prefix-правило (воркер только после процесса), `split_address()/process_of()/worker_of()`. Backward: `"proc"` (без точки) = только процесс — как сейчас.
2. Зафиксировать контракт «address-aware `MessageChannel`»: канал по qtype, доставляет по `process_of(targets)`; spec + docstring (реализация — P1).
3. Объявить `MESSAGE_TYPE_TO_CHANNEL` (COMMAND/SYSTEM→system-канал, DATA→data-канал, EVENT→event, STATE→state) как набор `register_route(MessageType, channel_name)` (контракт; проводка — P1).
4. Contract-тесты: парсинг/валидация адреса (воркер без процесса → ошибка), backward `"proc"`, таблица type→channel объявлена.
**Acceptance:** - [x] dotted-адрес парсится и валидируется (prefix), backward-совместим с плоским `targets` - [x] контракт address-aware канала и таблица `MESSAGE_TYPE_TO_CHANNEL` объявлены, покрыты тестами - [x] НЕ введены новые поля `kind`/`address` и новый Channel-Protocol (reuse `type`/`targets`/`IMessageChannel`) - [x] `make check` чист, framework-тесты зелёные.
**Out of scope:** проводка `send`/`receive` через каналы (P1); удаление старых путей.

> **P0.2 DONE** (`4e22426e`): `message_module/addressing/` (split_address/process_of/worker_of/subpath_of/normalize_targets + `AddressValidationError`) и `router_module/routing/` (`MESSAGE_TYPE_TO_CHANNEL` + `resolve_channel_kind` + `channel_name` + `resolve_route(s)`/`RouteDecision`). 54 contract-теста, 3000 framework зелёные, ruff+pyright чисты. **Ключевое решение по recon #1:** STATE — channel-kind, выводимый из `command="state.*"`, а НЕ член `MessageType` (нормализация `command`/`type`→kind ДО таблицы; неизвестный type → `UnknownMessageTypeError`, не тихий drop). Решения по recon #2/#3/#4/#6 зафиксированы в docstring `address_aware_channel.py`.

### Task P0.3 — ADR + обновление карты
**Level:** Senior (Opus) · **Assignee:** tech-writer/teamlead
**Goal:** Зафиксировать решения, синхронизировать индексы.
**Files:** `multiprocess_framework/DECISIONS.md` (+ `router_module/DECISIONS.md`), `COMMUNICATION_MAP.md` (пометить §5.1 как superseded этим планом), `python -m scripts.sync`.
**Steps:**
1. **ADR-COMM-001 (новая редакция):** «`router.send(message)` — единственный способ отправки; каналы по `kind` — канонический транспорт; channel-routing старого вида (`register_route`/FieldRouting.channel) удаляется». Why: изначальный замысел хаба; убираем 6 путей до 1.
2. **ADR-COMM-004:** «Иерархическая адресация `address=[process, worker, ...]`, prefix-routing, нижние уровни резолвятся внутри процесса».
3. Cross-ref: ADR-COMM-002 (ActionBus→domain) делегирован в `constructor-maturity P1`; ADR-COMM-003 (один FrameShmMiddleware + Claim Check) реализуется в P3.
4. В `COMMUNICATION_MAP.md` дописать врезку «§5.1 superseded планом transport-router-hub (владелец выбрал hub-with-channels)».
5. `scripts.sync` + `scripts/validate.py` (нет дрифта).
**Acceptance:** - [x] ADR-COMM-001/004 в DECISIONS, sync выполнен, validate без дрифта - [x] §5.1 помечена superseded.
**Out of scope:** код.

> **P0.3 DONE** (`c8e68832`): ADR-COMM-001 (новая редакция, заменяет §5.1) + ADR-COMM-002 (делегирован constructor-maturity P1) + ADR-COMM-003 (запланирован P3.1, recon #4) + ADR-COMM-004 (иерархическая адресация) в секции «Коммуникационная архитектура» глобального DECISIONS. Локальные: ADR-RTR-007 (routing-таблица), ADR-MSG-007 (addressing). §5.1 и старая редакция ADR-COMM-001 в `COMMUNICATION_MAP.md` помечены superseded. `scripts.sync` пересобрал ADR-INDEX (RTR/MSG-001…007), `validate.py` без дрифта. **P0 полностью закрыта.**

---

## P1 — Хаб на отправке (strangler; existing `send`+`register_route`, каналы оборачивают `queue_registry`)

**Цель:** оживить существующий путь `RouterManager.send → _resolve_channels → IMessageChannel.send` для реального IPC: зарегистрировать очереди `queue_registry` как address-aware `QueueChannel`, привязать `register_route(MessageType→channel)`. Старые `send_message`/`broadcast` становятся тонкими адаптерами над `router.send`. Паритет доказан. Ничего не удаляем.

> **P1 DONE** (`2f417169` + `9dd31d73`) — вышло **леаннее** замысла. Открытие: хаб-путь `router.send → _deliver_by_targets → queue_registry` УЖЕ построен долгом #1 (U1), а cross-process каналы `{proc}_{qtype}` уже регистрируются. Поэтому:
> - **P1.1/P1.2:** новый класс канала НЕ понадобился — `_deliver_by_targets` стал канонической address-aware доставкой; снят channel-guard (баг recon #3, дропал кадры), выбор qtype сведён в `_select_queue_type` (recon #5). type→`register_route`-проводка **отложена в P3** (паритет требует сохранить нынешнее правило qtype до развода Event/State-каналов).
> - **P1.3:** `send_to_process`/`send_message` → `router.send` (обход B1 убран, ~30→~12 строк). `broadcast` оставлен (отдельный fan-out, B7 почти мёртв).
> - **Верификация:** 2997 framework + паритет-тесты; **smoke прототипа end-to-end** — вебкамера→split→processors→stitcher→GUI, **дисплей FPS 14, stitcher 56 кадров, 0 ERROR** — кадры идут через новый `router.send`-путь. Прототип-фикс `auto_start` (`03e712cb`).
> - Контрол-плейн (heartbeat 8 процессов) и data-плейн (кадры) идут одним кодом — оба доказаны вживую.

### Task P1.1 — Address-aware QueueChannel над queue_registry + регистрация при init
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Подключить реальные очереди `queue_registry` в `ChannelRegistry` роутера через существующий `QueueChannel`/`MessageChannel`, с резолвом получателя из `targets`.
**Files:** `router_module/channels/queue_channel.py` (расширить address-aware, либо подкласс), регистрация при init процесса (`process_module/communication/process_communication.py` / `core/process_module.py` — там уже есть `register_channel`/`register_route`-вызовы). Тесты `router_module/tests` с фейковым queue_registry.
**Steps:** 1. `send(message)` резолвит очередь по `process_of(message["targets"])` + qtype (system/data) и кладёт через `queue_registry.send_to_queue` (тот же нижний транспорт). 2. `poll(timeout)` — над существующей `queue.get` (как сейчас в `receive`). 3. При старте процесса зарегистрировать `QueueChannel` для system/data и `register_route(MessageType.COMMAND/SYSTEM→system, DATA→data)`.
**Acceptance:** - [ ] сообщение через `router.send` ложится в ту же очередь `{proc}_{qtype}`, что и нынешний `send_to_queue` (паритет) - [ ] `poll` отдаёт те же сообщения - [ ] переиспользованы `QueueChannel`/`register_channel`/`register_route` (нет новых классов-дублей) - [ ] нулевой регресс framework-тестов.
**Out of scope:** Frame/Event/State каналы (P3); удаление прямых вызовов (P4).

### Task P1.2 — Оживить `RouterManager.send` для type→channel + targets-резолв
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Убедиться, что существующий `send`/`_resolve_channels` выбирает канал по `register_route(type)` и доставляет по `targets`, без `msg["channel"]`-костыля.
**Files:** `router_module/core/router_manager.py` (`_resolve_channels`/`_deliver_by_targets`). Тесты.
**Steps:** 1. Резолв канала: `register_route` по `MessageType` (а не только явный `msg["channel"]`). 2. `_deliver_by_targets` встроить КАК внутренний механизм address-aware канала (адрес→очередь) — не отдельный обходной путь. 3. Неизвестный type/нет канала → лог + ошибка (не тихий drop — закрыть silent-drop из находки U1).
**Acceptance:** - [ ] `router.send(Message(type=COMMAND, targets=["proc"]))` доставляется без явного `channel` - [ ] неизвестный type не теряется молча - [ ] `_deliver_by_targets` живёт внутри канала, а не рядом - [ ] тесты.
**Out of scope:** миграция отправителей (P4).

### Task P1.3 — send_message/broadcast → адаптеры над router.send (паритет)
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** `ProcessCommunication.send_to_process`/`send_message`/`broadcast` строят `Message`(`MessageAdapter`) и зовут `router.send` — без смены наблюдаемого поведения.
**Files:** `process_module/communication/process_communication.py`, `core/process_module.py`. Тесты паритета.
**Steps:** 1. `send_message(target, msg)` → `router.send` с `targets=[target]`, `type` из msg. 2. `broadcast` → через `router.send` (один механизм; убрать дубль логики `broadcast_message`). 3. Тест паритета: те же сообщения в тех же очередях, что и до.
**Acceptance:** - [ ] существующие e2e/IPC-тесты зелёные без изменения ассертов (паритет) - [ ] один механизм broadcast - [ ] прототип запускается (smoke) - [ ] кадры (data-plane) не сломаны.
**Out of scope:** удаление `send_message` API (останется адаптером до P4/P5 — после обсуждения).

---

## P2 — Иерархическая адресация + воркер-уровень

**Цель:** `address=[process, worker, ...]`; cross-process — в очередь процесса, воркер+ резолвится внутри процесса. Точка стыковки с `assigned_worker` (Фаза 2 плана processes-workers-runtime-debts).

> Терминология: ниже `address` = `split_address(targets[i])` из P0.2 (dotted-путь в существующем `Message.targets`). Новое поле НЕ вводим; `address[0]`=`process_of`, `address[1]`=`worker_of`.

### Task P2.1 — Адрес как список + prefix-валидация в транспорте
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Перевести доставку на `address: list[str]`; prefix-семантика.
**Files:** `message_module` (уже v2 из P0.2), `router_module/channels/*` (резолв по `address[0]`), `router_manager`. Тесты.
**Steps:** 1. Каналы доставляют в очередь `address[0]`. 2. Валидация: пустой address → ошибка; воркер без процесса невозможен (гарантировано формой списка). 3. `address` длиннее 1 — нижние уровни кладутся в билет, доставка по `[0]`.
**Acceptance:** - [x] доставка по `address[0]` идентична доставке по прежнему `target` - [x] билет несёт полный `address` получателю - [x] тесты prefix.
**Out of scope:** intra-process роутинг на воркер (P2.2).

> **P2.1 DONE** (`09cd95a6`): `_deliver_by_targets` переведён на иерархический адрес — `split_address(target)` валидирует prefix-правило, cross-process доставка идёт в очередь `process_of` (`address[0]`), нижние уровни (`address[1:]`) едут в билете под `_address` (transport-internal, как `_receive_info`) для intra-process резолва P2.2. **Паритет:** плоское имя (`len==1`) → исходный билет без копии (ноль изменений, горячий data-path кадров не трогается), та же очередь, тот же qtype (`_select_queue_type` не менялся — kind→channel остаётся в P3). Невалидный адрес → debug-лог + пропуск, не падение. Мультикаст — per-target копия с собственным `_address`. 5 тестов (`TestHierarchicalDelivery`), 3002 framework зелёные, ruff чист. **Решение:** в доставке НЕ зову `resolve_route`/`resolve_channel_kind` (он бросает `UnknownMessageTypeError` на живых `type="system_event"` B10) — беру только ось адреса; ось kind подключим в P3, чтобы не ломать паритет.

### Task P2.2 — Intra-process роутинг на воркер (address[1])
**Level:** Senior+ · **Assignee:** teamlead
**Goal:** Внутри процесса-получателя Router/диспетчер направляет билет на воркер по `address[1]` (in-process очередь/handler), без новых IPC-очередей.
**Files:** `router_module`/`dispatch_module` (роутинг по address[1] → worker-handler), `worker_module` (worker как адресуемый приёмник). Тесты.
**Steps:** 1. На приёме: если `len(address)>1`, диспетчер ищет worker-scoped handler/очередь. 2. Если воркер не найден/без обработчика → лог + дефолт (на процесс). 3. Связать с in-process `queue.Queue` паттерном (как `chain_queue`).
**Acceptance:** - [x] билет с `[proc, worker]` доходит до worker-приёмника внутри процесса - [x] отсутствующий воркер → дефолт+лог, не падение - [x] нет новых IPC-очередей на воркера.
**Out of scope:** исполнение pipeline по воркерам (это `assigned_worker` Фаза 2 — см. ниже).

> **РЕШЕНИЕ ВЛАДЕЛЬЦА (2026-05-31): ГИБРИД (кадры—трубы, команды—почта).** Доставка
> плагину-в-воркере расщеплена на две ортогональные оси:
> - **Кадры (data-plane, горячий путь)** → **М1 «трубы»**: статическая топология
>   in-process `queue.Queue` (assigned_worker вариант A, БЕЗ изменений). Кадры адресуются
>   cross-process только по имени процесса; внутри процесса — проводка очередей групп.
> - **Команды/конфиг (control-plane)** → **М2 «почта»**: иерархический адрес
>   `proc.worker[.…]`, Router на приёме кладёт билет в обработчик воркера.
>
> **P2.2 DONE** (`<hash>`): тонкий control-plane хук в `RouterManager` —
> `register_worker_handler`/`unregister_worker_handler` (in-process реестр по имени
> воркера) + `_route_to_worker` в `receive()`: билет с `_address[1]` и НЕ data-кадр →
> `handler(msg)`, иначе обычный process-dispatch. **Guard «кадры не уводим»**:
> `type=="data"` всегда идёт обычным путём (М1), даже если несёт `_address` — оси
> разведены в коде. Отсутствующий воркер → debug-лог + fallback на процесс (не падение).
> Нет новых IPC-очередей. 8 тестов (`TestWorkerHandlerRouting`); 3010 framework зелёные,
> ruff чист. **Smoke прототипа**: камера→split→process→stitcher→gui, дисплей показывает
> кадры (`DisplaySlot "ImageSlot"`), 0 ERROR — data-plane (трубы) не задет, kadry идут как
> прежде; control-plane (heartbeat) тоже жив. **Первый продакшн-потребитель** worker-handler
> придёт с фичей «команда/конфиг плагину-в-воркере» из Pipeline (будущий заход).

### Task P2.3 — Стыковка с assigned_worker (реконсиляция плана)
**Level:** Senior · **Assignee:** teamlead
**Goal:** Зафиксировать, что «воркер как адресуемая единица» (P2.2) — это дом для `assigned_worker`; обновить план processes-workers-runtime-debts.
**Files:** `multiprocess_prototype/plans/processes-workers-runtime-debts.md` (врезка), этот план.
**Steps:** 1. Описать: PipelineExecutor-группа воркера потребляет из worker-адресуемой in-process очереди (P2.2), а не из изобретённого отдельно транспорта. 2. Решить порядок (см. §Сиквенс): либо assigned_worker Фаза 2 ждёт P2, либо её 2.3-handoff реализуется поверх P2.2.
**Acceptance:** - [x] в обоих планах зафиксирована единая модель воркер-адресации - [x] нет двух разных транспортов для воркера.
**Out of scope:** сама реализация группировки (живёт в processes-workers-runtime-debts).

> **P2.3 DONE** (`<hash>`): **реконсиляция = разведение осей, а не выбор одного транспорта.**
> Первоначальная формулировка P2.3 («PipelineExecutor-группа потребляет из
> worker-адресуемой очереди P2.2») оказалась НЕВЕРНОЙ для data-plane — она смешивала две
> ортогональные оси. Гибрид-решение владельца разводит их так, что **двух транспортов для
> одной задачи нет**:
> - **Data-plane кадров между группами воркеров** = М1 «трубы» (статическая топология
>   in-process очередей, assigned_worker Фаза 2 вариант A **без изменений** — её текст про
>   «адресацию до воркера в отдельном плане» теперь КОРРЕКТЕН для кадров).
> - **Control-plane команд воркеру** = М2 «почта» (P2.2 worker-handler по `_address`).
>
> Это НЕ два транспорта для воркера, а **один транспорт на каждую ось груза** (кадр vs
> команда) — ровно дух плана («что за груз → свой канал»). assigned_worker Фаза 2 НЕ
> переписывается и НЕ ждёт P2.2 (её handoff кадров не адресный). Врезка добавлена в
> `processes-workers-runtime-debts.md`.

---

## P3 — Каналы по kind: Frame / State / Event (манифест)

**Цель:** перевести крупные типы груза на каналы; слить дубли (§5.2 аудита).
- **P3.1 FrameChannel + слияние FrameShmMiddleware.** Один middleware (framework), Claim Check; `SourceProducer`/`PipelineExecutor` шлют кадры через `router.send(kind=frame)`. Слить два `FrameShmMiddleware` и два ring-buffer в по одному (ADR-COMM-003).
- **P3.2 StateChannel.** Обернуть путь `DeltaDispatcher` под `router.send(kind=state)` (уже U1/долг #1); удалить legacy `process_full_status` broadcast.
- **P3.3 EventChannel.** Канонический cross-process pub/sub; убрать `EventManager` dual-write (очередь+callbacks) → один путь через канал.
> Детализация Task P3.x — при старте фазы (investigation-first).

## P4 — Миграция отправителей + удаление обходов и дублей (манифест)

- **P4.1** `CommandSender` ручной dict → единая фабрика Message (убрать «третий способ создать сообщение», §3.2).
- **P4.2** Heartbeat, register-релеи, broadcasts → `router.send`.
- **P4.3** Сделать `queue_registry.send_to_queue` и прямой SHM **приватными деталями каналов**; sentrux-правило: запрет прямых вызовов вне `channels/`.
- **P4.4** Убрать двойную диспетчеризацию (`message_dispatcher → lambda → CommandManager.dispatcher`): регистрировать прикладные handler напрямую в `message_dispatcher` (§3.5).
- **P4.5** Слить дубли: один ring-buffer; удалить top-level `frontend/bridge.py` (затенённый дубль); StateStore — один набор `state.*` handler (не дважды).

## P5 — Изоляция/удаление мёртвого кода + вынос в framework + инварианты (манифест)

> **ПРАВИЛО ВЛАДЕЛЬЦА (2026-05-31): НИЧЕГО НЕ УДАЛЯТЬ АВТОМАТИЧЕСКИ.** Перед удалением
> КАЖДОГО модуля/символа — отдельное обсуждение с владельцем и явное одобрение. Многие
> «мёртвые» модули — намеренный конструктор-задел (память `priority_product_over_engine`,
> `constructor_modularity`). Дефолтное действие — **изолировать** (убрать из публичного
> `__init__`, пометить deprecated, перестать импортировать), а не `rm`. Удаление —
> только после approval по каждому пункту.

- **P5.0 (gate, обязателен первым)** Сформировать таблицу кандидатов на удаление/изоляцию
  (из §3.4 + recon P0.1, **кроме ActionBus** — он в `constructor-maturity P1`): для каждого —
  доказательство «мёртв» (codegraph callers=0), решение владельца **[обсудить]**:
  `удалить` | `изолировать` | `оставить (задел)`. Кандидаты: `chain_module`
  ScenarioManager/ChainRunnable/Dag/WorkerPoolDispatcher; `dispatch_module`
  PATTERN/FALLBACK/CHAIN/BaseDispatcher/scenarios; `RouterSchemaAdapter`/`routing_map`/
  `register_channel_scenario`; `message_factory.*`; `CommandAdapter.execute_via_message`;
  `MessageAdapter.create_message`; `FrontendManager`+`FrontendRegistersBridge`;
  `LoggerManager._route_via_router`; `SQLManager.execute_command`-surface;
  `PreviewWindow` SHM-subscribe; top-level `frontend/bridge.py`.
  > `register_route`/`register_channel` — **НЕ кандидаты** (живы: `process_module`,
  > `router_adapter`, `frame_router_setup` зовут при init). Депрекейтим только неиспользуемый
  > channel-**routing-by-pattern**, не саму регистрацию каналов.
- **P5.1** Выполнить решения P5.0 ТОЛЬКО по одобренным пунктам (по одному, с verify после каждого).
- **P5.2** Sentrux-инварианты: единственный вход отправки (`router.send`), запрет обходов
  (`send_to_queue`/SHM вне `channels/`), запрет импорта изолированных модулей; обновить
  `COMMUNICATION_MAP.md` до «as-built»; DECISIONS sync.
- **P5.3** Граница framework: хаб+каналы — во `framework`, прототип только формирует билеты;
  layer-rules в `.sentrux/rules.toml`. (Согласовать с `constructor-maturity P6`.)

---

## Связь с assigned_worker (processes-workers-runtime-debts, Фаза 2)

Фаза 2 того плана (вариант A: PipelineExecutor-группа на воркер + in-process `queue.Queue` handoff) — это **прикладное исполнение** на уровне «воркер», а P2 этого плана даёт **транспортный дом** для адреса «воркер». Они встречаются в P2.2/P2.3.

**Развилка сиквенса (решение владельца):**
- **Вариант S1 (рекомендуется):** сделать P0–P2 этого плана ПЕРЕД assigned_worker Фаза 2 → исполнение по воркерам строится сразу на правильной иерархической адресации (никаких временных транспортов, «без костылей»).
- **Вариант S2:** доделать assigned_worker Фаза 2 на текущем `chain_queue` (как в её ТЗ, уже учтён targets-транспорт), затем P2 поглотит её адресацию. Быстрее к фиче, но возможен мелкий повторный заход в 2.3-handoff.

`processes-workers-runtime-debts.md` уже содержит врезку «Связь с аудитом коммуникаций» (targets-транспорт + `chain_queue` + запрет мёртвых движков) — она совместима с обоими вариантами.

---

## Риски

| Риск | Severity | Митигирование |
|---|---|---|
| Регресс data-plane (кадры) при введении FrameChannel | HIGH | Claim Check (пиксели в SHM, не в шине); паритет-тесты P3.1; нулевой регресс — отдельный acceptance |
| «Большой взрыв» / прототип ломается | HIGH | strangler: старые API живут адаптерами до P4/P5; smoke-запуск после каждой фазы |
| Двойная диспетчеризация / скрытые потребители | MEDIUM | P0.1 investigation-first; codegraph callers перед удалением |
| Пересечение с constructor-maturity (ActionBus, framework-вынос) | MEDIUM | явное делегирование P1/P6 туда; cross-ref, не дублировать |
| fire-and-forget (потеря результата команды) | MEDIUM | вне scope транспорта; подтверждение через StateStore (живой долг #1), как в assigned_worker |
| Иерархия адреса ломает Dict-at-Boundary | LOW | `address: list[str]` — JSON-safe; backward-shim `target`→`[target]` |

## Верификация (общая)

- `python scripts/run_framework_tests.py` / `make test` — зелёные после каждой фазы.
- `make check` (ruff + pyright + bandit).
- Smoke прототипа (`/run-proto` + qt_snapshot) — после P1, P2, P3 (прототип запускается, кадры идут, GUI живой).
- `mcp__sentrux__session_start` baseline перед P0 → `session_end` после каждой фазы (дельта качества; цель — рост за счёт удаления дублей/мёртвого кода).
- Три «билета» end-to-end как приёмочный сценарий хаба: команда `worker.create`, кадр с камеры, state-дельта — каждый проходит `router.send → Channel → receive → handler`.

## Коммиты

- Каждая фаза — серия `refactor(router)`/`feat(router)` коммитов, `Layer: framework` (P4/P5 — частично `mixed`). `Refs: plans/2026-05-31_transport-router-hub/plan.md`.
- Создание/закрытие фаз — отдельный `docs(plans):` коммит.
- ADR-COMM-001/004 — в составе P0.3.
