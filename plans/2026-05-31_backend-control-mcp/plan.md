# backend-control-mcp — Headless backend-driver + интроспекция + MCP

- **Дата:** 2026-05-31 · **Зона:** infra/tooling (+ framework для команд интроспекции)
- **Ветка (создать при старте P1):** `feat/backend-control-mcp` (НЕ автоматически; сейчас
  uncommitted работа Этапа 2 на `feat/pipeline-live-control`)
- **Статус:** PLAN. P0 recon ⏳ next.
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

## P0 — Recon + ADR (как driver-процесс крепится к RouterManager, что доступно для интроспекции)

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
- [ ] `introspect.handlers(<process>)` возвращает реальные ключи (проверка: preprocessor НЕ
      содержит `register_update` — воспроизводит находку Этапа 2)
- [ ] `introspect.registers/status` возвращают корректные dict
- [ ] `python scripts/run_framework_tests.py` зелёный; unit-тесты команд
**Module contract:** lite (новые команды + тесты)

---

## P2 — Driver-процесс в графе (ProcessModule + thin API через RouterManager)

**Level:** Senior (teamlead) · **Assignee:** teamlead
**Goal:** driver = процесс-сиблинг GUI в blueprint (спавнится ProcessManager'ом, имеет
RouterManager). Тонкий API поверх `router.send`/CommandSender: `send_command(target, cmd,
args)`, `send_system_command`, `introspect_*` (request-response через RouterManager),
`get_topology`, `set_register(process, plugin, field, value)`. Без бизнес-логики — обёртка.

**Files (ориентир, уточнить в P0):**
- driver как ProcessModule-наследник (control-процесс) + worker-цикл; добавляется в
  blueprint под гейтом `BACKEND_CTL=1`. Reuse CommandSender/ProcessManagerProxy и
  topology loader из `backend/launch.py`.
- регистрация driver-процесса в сборке (`backend/launch.py`/blueprint) — опциональный
  процесс рядом с GUI.

**Acceptance:**
- [ ] Driver-процесс поднимается в графе, шлёт `router.send` любому процессу и **получает
      ответ через RouterManager** (correlation_id)
- [ ] Послать `register_update` в живой процесс и **через introspect подтвердить** применение
      (или отсутствие приёмника — воспроизвести находку Этапа 2)
- [ ] Тот же dict-протокол, что GUI (паритет); ноль дублирования логики команд; ноль сайд-каналов к процессам
- [ ] Аккуратная остановка (PID-specific, не глобальный taskkill — memory `feedback_no_global_taskkill`)
**Module contract:** full (новый модуль `control/` — README + Protocol + contract-тесты)

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
