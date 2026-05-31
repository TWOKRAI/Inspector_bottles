# backend-control-mcp — Headless backend-driver + интроспекция + MCP

- **Дата:** 2026-05-31 · **Зона:** infra/tooling (+ framework для команд интроспекции)
- **Ветка (создать при старте P1):** `feat/backend-control-mcp` (НЕ автоматически; сейчас
  uncommitted работа Этапа 2 на `feat/pipeline-live-control`)
- **Статус:** P0 recon ✅ · P0.5 ✅ (`1a1b6b9b`) · P1 ✅ (`df8fa01f`) — ветка
  `feat/backend-control-mcp`. **Решение транспорта пересмотрено:** socket-канал в RouterManager
  вместо driver-процесса-в-графе (см. «P0 ИТОГ» ниже). **P2-P3 — ПАУЗА на переоценку** (решение
  владельца 2026-05-31): ценность фронт-лоадед в P0.5+P1; перед socket+MCP оценить более дешёвую
  альтернативу — headless in-process харнесс (`router.request(...)` напрямую, без сокета/MCP).
- **Слой:** mixed (framework: generic introspection-команды; prototype/infra: driver+MCP)

## Замысел (владелец, 2026-05-31)

Сделать **MCP-сервер параллельно GUI** — он говорит теми же командами/структурами
(конфиги, топологии), что и GUI, поверх **того же транспорта** (RouterManager + dict-
протокол). Тогда бэкенд можно **отрабатывать напрямую** через MCP (целиться, слать,
читать состояние), не сражаясь с qt-mcp, и **отлаживать бэкенд и фронтенд раздельно** —
не гадая, где проблема. Промежуточный слой отработки бэкенда.

**Мотивация (доказана сессией pipeline-live-control Этап 2, 2026-05-31):** диагностика
«параметр не применяется live» заняла ~30 шагов драйва qt-mcp (искать viewport, считать
DPR, кликать QGraphicsItem) — а реальный блокер был backend (у плагина нет worker-side
приёмника `register_update`). Команда интроспекции `introspect.handlers(preprocessor)`
показала бы это **мгновенно**, без единого клика.

## Принципы (НЕ изобретать — переиспользовать)

- **РЕШЕНИЕ ВЛАДЕЛЬЦА (2026-05-31): общение driver↔бэкенд — ТОЛЬКО через RouterManager.**
  Никаких сайд-каналов (сокеты/файлы/прямой queue_registry) для связи с процессами. Driver
  шлёт `router.send(message)` и принимает ответы тем же хабом. Следствие архитектуры:
  RouterManager живёт **по процессу** и использует shared `queue_registry` (очереди
  раздаются при спавне ProcessManager'ом) — значит **driver обязан быть процессом в графе
  системы** (сиблинг GUI, спавнится ProcessManager'ом). Внешний процесс к этим очередям не
  подключить. **MCP-сокет — ТОЛЬКО граница Claude↔driver**; всё внутрь системы и ответы
  обратно идут чистым RouterManager.
- GUI уже **тонкий клиент** dict-протокола: `CommandSender.send_command/send_system_command`
  ([command_sender.py](../../multiprocess_framework/modules/frontend_module/bridge/command_sender.py)),
  `ProcessManagerProxy`, всё через `RouterManager`. MCP-driver = **ещё один такой фронтенд**,
  тот же транспорт. Dict at Boundary это прямо допускает.
- Интроспекция-команды строятся как generic builtin-команды процесса — паттерн
  `worker.create/...` из [builtin_commands.py](../../multiprocess_framework/modules/process_module/commands/builtin_commands.py)
  (регистрация в `CommandManager`, `tags=["system"]`).
- Транспорт уже единый (RouterManager-хаб, transport-router-hub P0-P2 на ветке). Driver
  работает на текущем транспорте; с transport P3 (Event/State-каналы) станет чище, но не ждёт его.

## Связанные планы

- **transport-router-hub** (`plans/2026-05-31_transport-router-hub/`) — транспорт, на котором
  ездит driver. Не дублировать: driver — потребитель хаба, не строит его.
- **pipeline-live-control** (`plans/2026-05-31_pipeline-live-control/`) — фича, которую этим
  driver'ом быстрее отлаживать/доделывать (Этап 2 worker-side, Этап 3 ноды).

## Связанные memory

`project_transport_router_hub`, `project_pipeline_live_control_stage1`,
`project_priority_product_over_engine` (тулинг не должен подменять продукт — держать тонким),
`feedback_constructor_modularity` (один backend-API, несколько фронтендов),
`feedback_qt_mcp_smoke_verification`.

---

## P0 ИТОГ (recon DONE 2026-05-31) — пересмотр транспорта на socket-канал

Recon (investigator) проверил 5 допущений. Оценка жизнеспособности:

| # | Пункт | Статус | Факт |
|---|-------|--------|------|
| 1 | Request-response через RouterManager | 🟡 | Транспорт fire-and-forget. Фундамент есть (`Message.request_id`, `MessageAdapter.response()`, `correlation_id` в PM), но путь сломан: ответ `_handle_process_command` шлётся **без `targets`** ([process_manager_process.py:876](../../multiprocess_framework/modules/process_module/process_manager_process.py#L876)) → теряется. **Prerequisite** (~130 строк). |
| 2 | Привязка driver к RouterManager | 🟢 | GUI — обычный `ProcessModule` в blueprint. |
| 3 | Доставка к любому процессу | 🟢 | `_deliver_by_targets` + иерархия `proc.worker` работают. |
| 4 | Источники интроспекции | 🟢 | Геттеры уже есть: `command_manager.get_commands()`, `message_dispatcher.get_all_handlers()`, `registers_manager.model_dump_all()`, `get_all_processes_status()`. P1 — тонкая обёртка. |
| 5 | MCP-сервер в потоке | 🟢 | `WorkerManager.create_worker` даёт поток; главный цикл не блокирует. TCP, не stdio. |

### РЕШЕНИЕ ВЛАДЕЛЬЦА (2026-05-31): socket-канал вместо driver-в-графе

P0 предполагал «driver обязан быть процессом в графе, т.к. внешний процесс не подключить
к shared `queue_registry`». Владелец предложил **инверсию, под которую и делался RouterManager**:
добавить `SocketChannel(MessageChannel)` (сиблинг `QueueChannel`) — внешний процесс
**подключается** к нему. Подтверждено по коду: `RouterManager.register_channel(IMessageChannel)`
([router_manager.py:458](../../multiprocess_framework/modules/router_module/core/router_manager.py#L458))
+ `register_route` — это by-design точка расширения.

- **Хост канала** — один живой процесс (естественно ProcessManager, хаб): `register_channel(SocketChannel)`.
  Accept-loop в потоке (`WorkerManager`). НЕ новый сиблинг-процесс — канал внутри существующего.
- **Inbound:** внешний driver шлёт JSON-dict `targets=[process]` → `SocketChannel` → `router.send`
  → `_deliver_by_targets` → очередь процесса (п.3 зелёный).
- **Outbound (ответ):** prerequisite request-response (п.1), `reply_to=имя socket-канала` + `correlation_id`.
- **Сериализация:** JSON (Dict at Boundary). Кадры/SHM через сокет НЕ гоняем — драйверу не нужны.
- **Совпадает с transport-router-hub P3** («ещё один IMessageChannel»), не плодит второй транспорт.
- **Граница:** socket = ровно Claude↔driver. dev-гейт + localhost-bind.

**Связь с продуктом:** resize-ретрофит (commit 4327ccf8) доказал — live-параметры работают
**без** этого тулинга. Socket-driver = ускорение отладки бэкенда, не на критическом пути фич.
Держать тонким (memory `priority_product_over_engine`).

---

## P0 — Recon + ADR (исходные вопросы — ниже, для истории; итог выше)

**Level:** Senior (investigator/teamlead) · **Assignee:** investigator → ADR teamlead
**Goal:** зафиксировать механику driver-процесса-в-графе (общение ТОЛЬКО через
RouterManager — решение владельца) и реальные источники интроспекции.

**Вопросы recon (ответить ДО кода):**
1. **Регистрация driver-процесса в графе.** Driver = процесс-сиблинг GUI (ProcessModule),
   добавляется в blueprint и спавнится ProcessManager'ом → получает `RouterManager` +
   shared `queue_registry`. Проверить `SystemLauncher.add_process` / `ProcessManagerProcess`
   спавн; подтвердить, что сиблинг шлёт **любому** процессу через `router.send` (сегодня в
   Этапе 2 был open-вопрос: GUI→произвольный worker — доставка дошла до очереди, но это
   надо подтвердить как штатный путь). GUI остаётся опциональным (driver + опц. GUI).
2. **Request-response через RouterManager (НЕ сайд-канал).** Интроспекции нужен ОТВЕТ.
   Механизм: `correlation_id` + ответный `router.send` обратно driver'у (transport-router-hub
   Roadmap «результат команды»), либо выделенный control-канал ответа. Выбрать и
   согласовать с transport-router-hub (не плодить параллельный механизм).
3. **MCP-транспорт = ТОЛЬКО граница Claude↔driver.** Driver-процесс держит отдельный
   поток/worker с MCP-сервером (stdio/TCP), который транслирует вызовы Claude в
   `router.send` и ждёт RouterManager-ответ. Главный цикл процесса не блокировать. Как
   Claude подключается (mcp server config).
4. **Источники интроспекции** (ответы едут через RouterManager):
   - процессы: ProcessManager/ProcessMonitor (heartbeat, registry) + топология;
   - регистры: per-process RegistersManager (команда `introspect.registers` процессу);
   - **handlers**: знает только router каждого процесса (`message_dispatcher` ключи +
     `CommandManager` команды) → команда `introspect.handlers` процессу (P1);
   - топология: `topology_store`/recipe.
5. **Безопасность/изоляция:** dev-инструмент. Гейт (driver-процесс в blueprint только при
   `BACKEND_CTL=1`), не поднимать в проде по умолчанию.

**Deliverable:** `recon.md` + ADR (как driver крепится к RouterManager, request-response
через хаб, MCP только на границе Claude↔driver, список интроспекции). **Module contract:** docs-only.

---

## P1 — Generic introspection-команды в процессах (framework)

**Level:** Middle+ (developer) · **Assignee:** developer
**Goal:** каждый процесс отвечает на запросы «что у меня есть» — handlers, registers,
status. Это и есть инструмент, который ловит баги вида «нет приёмника register_update».

**Files:**
- [builtin_commands.py](../../multiprocess_framework/modules/process_module/commands/builtin_commands.py)
  — добавить `introspect.handlers` / `introspect.registers` / `introspect.status`
  (по образцу worker.*; `tags=["system"]`). Возвращают dict (Dict at Boundary).
- (опц.) аналог в ProcessManager: `introspect.processes` (список живых процессов + статусы).

**Steps:**
1. `introspect.handlers` → ключи `message_dispatcher` (router) + команды `CommandManager`.
2. `introspect.registers` → имена регистров + поля (из worker-side RegistersManager, если есть;
   иначе пусто — что само по себе диагностично, как в Этапе 2).
3. `introspect.status` → имя процесса, воркеры (имена/статусы), статус процесса.
4. Request-response **через RouterManager** (решение владельца — без сайд-каналов):
   ответ интроспекции едет обратно driver'у `router.send`'ом с `correlation_id` (механизм
   из P0), а не через отдельный сокет/файл.

**Acceptance:**
- [x] `introspect.handlers(<process>)` возвращает реальные ключи (проверка: preprocessor НЕ
      содержит `register_update` — воспроизводит находку Этапа 2) — `df8fa01f`
- [x] `introspect.registers/status` возвращают корректные dict — `df8fa01f`
- [x] `python scripts/run_framework_tests.py` зелёный; unit-тесты команд (10 шт., framework 3045 passed)
**Module contract:** lite (новые команды + тесты)
**Статус:** ✅ DONE (`df8fa01f`, ветка `feat/backend-control-mcp`)

---

## P0.5 — Prerequisite: request-response через RouterManager (framework)

**Level:** Senior (teamlead) · **Assignee:** teamlead
**Goal:** ответ на команду доходит до отправителя (сейчас теряется — recon п.1).
**Steps:** ответ адресуется (`targets=[sender]`/`reply_to`) + `correlation_id`; на стороне
отправителя — реестр pending + `await_response(correlation_id, timeout)`. Generic, не только PM.
**Acceptance:** `[x]` команда из процесса A в процесс B возвращает результат A; тест; без регрессий — `1a1b6b9b`.
**Why:** без ответа интроспекция слепа. **Module contract:** lite.
**Статус:** ✅ DONE (`1a1b6b9b`). Реализация: `RouterManager.request()/reply_to_request()/
_resolve_pending` + резолвер в `receive()` (correlation_id). Найдены и закрыты **две** дыры:
PM `_handle_process_command` (ответ без `targets`) **и** generic command-путь
(`ProcessLifecycle._make_command_handler` — результат `handle_command` раньше выбрасывался).
Ответ едет system-очередью (`queue_type="system"`). Контракт: `request()` нельзя звать из
приёмного потока (дедлок). 16 тестов.

---

## P2 — SocketChannel + тонкий внешний driver (вместо driver-в-графе)

**Level:** Senior (teamlead) · **Assignee:** teamlead
**Goal:** `SocketChannel(MessageChannel)` в `router_module/channels/` (сиблинг `QueueChannel`),
хостится в ProcessManager (`register_channel` + accept-loop в `WorkerManager`-потоке). Внешний
тонкий driver-модуль (`message_module` + socket-клиент) шлёт те же `Message`/dict, что GUI по
queue: `send_command(target, cmd, args)`, `send_system_command`, `introspect_*` (request-response
из P0.5), `get_topology`, `set_register(process, plugin, field, value)`. Без бизнес-логики.

**Files (ориентир):**
- `multiprocess_framework/modules/router_module/channels/socket_channel.py` — новый канал
  (JSON wire; кадры/SHM НЕ гоняем). Регистрация в хосте через `register_channel`/`register_route`.
- внешний driver-модуль (infra) + socket-клиент; dev-гейт `BACKEND_CTL=1` + localhost-bind.

**Acceptance:**
- [ ] Внешний процесс подключается к SocketChannel, шлёт `router.send` любому процессу и
      **получает ответ** (correlation_id, P0.5)
- [ ] Послать `register_update` в живой процесс и **через introspect подтвердить** применение
- [ ] Тот же dict-протокол, что GUI (паритет); ноль дублирования логики; кадры не через сокет
- [ ] Аккуратная остановка (PID-specific — memory `feedback_no_global_taskkill`)
**Module contract:** full (новый канал — README + contract-тесты; + driver-модуль README)

---

## P3 — MCP-обёртка над driver

**Level:** Senior (teamlead) · **Assignee:** teamlead
**Goal:** выставить driver как MCP-сервер — Claude управляет бэкендом напрямую.

**Инструменты (минимальный набор):**
- `send_command(target, cmd, args)` / `send_system_command(cmd, args)`
- `list_processes` / `list_handlers(process)` / `get_registers(process)` / `get_status(process)`
- `get_topology` / `set_register(process, plugin, field, value)`

**Acceptance:**
- [ ] MCP-сервер регистрируется (mcp config), Claude вызывает инструменты против живого бэкенда
- [ ] Сценарий Этапа 2 воспроизводится через MCP без GUI: послать параметр → introspect →
      увидеть результат/блокер
- [ ] Dev-гейт (`BACKEND_CTL=1`), не в проде по умолчанию
**Module contract:** impl + README

---

## P4 (опционально) — Сценарии/replay, snapshot-diff

Запись последовательности команд + повтор; diff состояния процесса до/после. Для
регрессионных backend-сценариев без GUI. Делать только если P1-P3 окупились.

---

## Verify (общий)

- `python scripts/run_framework_tests.py` зелёный после каждой фазы.
- Smoke: driver/MCP воспроизводит находку Этапа 2 (`introspect.handlers preprocessor` без
  `register_update`) — самопроверка ценности инструмента.
- `session_start` baseline ПЕРЕД P1, `session_end` после (sentrux).
- Остановка бэкенда: PID-specific (`taskkill /PID <root> /T /F`), не глобально.
