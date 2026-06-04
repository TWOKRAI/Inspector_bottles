# Plan: Здоровый редизайн телеметрии — процесс сам публикует метрики (self-publish)

- **Slug:** telemetry-self-publish-redesign
- **Дата:** 2026-06-04
- **Статус:** READY — стартовать в новой (после /compact) сессии
- **Ветка:** `feat/comm-system-target-architecture` (продолжение telemetry-A)
- **Родитель:** [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md) (целевая «D»), [`comm-system-execution-order.md`](comm-system-execution-order.md) S0

> **Зачем этот план.** Несколько агентов подряд НЕ смогли зажечь FPS в карточках «Процессы». Владелец верно указал: **если простую вещь раз за разом не сделать — виновата архитектура, а не исполнители.** Этот план фиксирует корень (диагностирован в сессии 2026-06-04) и здоровое решение.

---

## Что УЖЕ работает (не трогать, закоммичено)

- **Статус-индикаторы ЗЕЛЁНЫЕ** — qt-mcp подтверждено. Коммиты:
  - `4e186997` Task 1.1 — доставка state-дельт IO→Qt через `DataReceiverBridge` (убран `_StateDeltaEmitter`/`invokeMethod`, молча терявший дельты в PySide6 6.10).
  - `965da540` Task 4.1 — replay закэшированного значения при `GuiStateBindings.bind()` (ленивая вкладка сразу подхватывает статус).
- **S1 observability Phase 1** — `446cca0e` на ветке `feat/observability-control-plane` (reconfigure CRM + invalidate cache, 153 теста).

## Корень проблемы (диагноз сессии 2026-06-04)

В телеметрии **ДВЕ разные архитектуры доставки, склеенные вместе:**

**Путь СТАТУСА (РАБОТАЕТ):** `процесс → _publish_state → дерево StateStore → IPC → GUI bridge → биндинг → карточка` (~6 хопов, проверен, зелёный).

**Путь FPS/Latency/health (НЕ РАБОТАЕТ) — лишний хрупкий средний участок:**
```
воркер.get_cycle_metrics → heartbeat-сообщение → ProcessManager._on_heartbeat_received →
PM агрегирует workers_status → _publish_state → дерево → IPC → GUI → биндинг   (8+ хопов, 2 процесса)
```
Зависит ДОПОЛНИТЕЛЬНО от: роутинга heartbeat + сериализации `workers_status` + центральной агрегации. Любой хоп падает **молча** → «—»/«0.0».

**Факты из диагностики:**
- Карточка camera_0 показывала `FPS: 0.0` (форматтер `{v:.1f}`) → `processes.camera_0.state.fps` публикуется ~нулём, не отсутствует.
- Диагностика `[FPS-DIAG]`/`[HB-DIAG]` в `_on_heartbeat_received` / `_publish_process_aggregate` **не сработала ни разу** → центральная heartbeat-агрегация (Task 3.1, коммит `7f81383a`) живьём не отрабатывает (heartbeat→`_on_heartbeat_received` для метрик не доезжает).
- Статус/uptime работают, потому что идут **другими** путями ProcessMonitor (`_broadcast_status_change`, monitoring-loop `_publish_uptime`), а НЕ через heartbeat-агрегат.
- `SourceProducer`/`PipelineExecutor`/`DataReceiver` корректно считают `effective_hz` локально (`CycleMetricsRecorder`, коммит `7f81383a`) — данные ЕСТЬ у процесса, проблема только в доставке через посредника.
- GUI frame-counting (считать кадры на пути дисплея) **не подходит** для FPS источника: кадры идут camera→detector→painter→GUI, до GUI доезжает только финальная стадия, не camera_0. Проверено: при frame-meter camera_0 оставался 0.0.

**Вывод:** убрать средний участок (heartbeat → центральный PM-агрегат) для GUI-метрик. heartbeat оставить ТОЛЬКО для liveness/timeout (его прямое назначение).

## Здоровое решение: процесс сам публикует свои метрики

> **Каждый процесс публикует `processes.{self}.state.fps` / `state.latency_ms` НАПРЯМУЮ в дерево StateStore через свой `state_proxy` — тем же путём, что и статус (который зелёный).**

Одна проверенная цепочка `процесс → дерево → GUI`. Без heartbeat-агрегата, без центрального посредника, без glob-матчинга по тысячам дельт. Совпадает с целевой «D» из родительского плана, но проще (без центрального снапшота — каждый репортит себя).

---

## Задачи

### Task 1 — Self-publisher метрик в процессе
**Level:** Senior (Opus) **Assignee:** teamlead
**Goal:** Каждый GenericProcess (и любой процесс с loop-воркерами) периодически публикует свой агрегат `processes.{self}.state.fps`/`state.latency_ms` в дерево StateStore через `state_proxy.set(...)`.
**Где:**
- Источник метрик уже есть: `WorkerManager.get_all_workers_status()` → у воркеров `effective_hz`/`cycle_duration_ms` (через `get_cycle_metrics`, коммит `7f81383a`).
- Точка публикации: лёгкий таймер/тик В САМОМ ПРОЦЕССЕ (например в `ProcessModule`/`GenericProcess` — отдельный мелкий loop-воркер «telemetry_reporter» ИЛИ в существующем heartbeat-таймере, но публикуя НЕ в heartbeat-msg, а прямо в дерево через `state_proxy`).
- Агрегат: `state.fps` = max(`effective_hz`) по running-воркерам; `state.latency_ms` = max(`cycle_duration_ms`). Нет hz → не публиковать (карточка «—»).
- **Нужен `state_proxy` в каждом процессе:** проверить, есть ли он у дочерних процессов (у GUI есть `GuiStateProxy`; у backend-процессов — есть ли `StateProxy`?). Если нет — добавить тонкий `StateProxy` (server_target="ProcessManager"), он уже умеет `set()` → IPC → StateStoreManager (тот же путь, что статус).
**Acceptance:**
- [x] qt-mcp: вкладка «Процессы» → camera_0/detector FPS — ЧИСЛО (не «—»/«0.0»), Latency — число. **DONE b6ce2bb8** (camera_0 19.6 / detector 24.0 / painter 19.7 FPS, latency 47/2/1 ms).
- [x] `state.fps` приходит из самого процесса (probe/лог), НЕ из `_on_heartbeat_received`. **DONE** (self-publish в `ProcessHeartbeat._publish_metrics_to_tree`).
**Out of scope:** не трогать статус-путь (работает), не трогать кадры.

> **Найдено по ходу (b6ce2bb8):** одного self-publish было мало. consumer-воркеры
> (DataReceiver/PipelineExecutor) реально крутили ~21 цикл/с (cycles росли), но
> `effective_hz=0.0`, т.к. `CycleMetricsRecorder` считал `1/cycle_duration`, а
> длительность мерилась `time.monotonic()` — на Windows гранулярность ~15 мс →
> sub-мс работа округлялась в 0. Фикс: `effective_hz` = частота **завершения**
> циклов (интервал между `record()` через `perf_counter`); consumer-раннеры
> перешли на `perf_counter`. camera_0 работала и раньше только потому, что её
> цикл включает ~47 мс throttle-sleep (> гранулярности).

### Task 1b — Per-worker телеметрия (доп. запрос владельца) — DONE
**Goal:** видеть время цикла КАЖДОГО воркера (а не только агрегат процесса), чтобы находить узкие места. Процесс = время самого медленного воркера (max), воркеры — каждый своё.
**Сделано:**
- `61b02761` — backend: self-publish per-worker `processes.{proc}.workers.{w}.status/effective_hz/cycle_duration_ms`.
- `7e59e259` — GUI: `GuiStateBindings.bind_fanout` (переиспользуемый fan-out с replay) + `SingleProcessPanel` обнаруживает рантайм-воркеров из телеметрии и подмешивает в таблицу read-only строками. Раньше таблица показывала только конфиг-топологию (`get_workers()`), без рантайм-воркеров пайплайна (`data_receiver`/`pipeline_executor`/`source_producer_*`).
**Acceptance:** [x] qt-mcp: detector → data_receiver 23.3 Гц/1.4 мс, pipeline_executor 23.6 Гц/2.0 мс — живые per-worker значения.

### Task 2 — Убрать heartbeat→центральный агрегат для метрик
**Level:** Middle+ **Assignee:** developer (после Task 1)
**Goal:** Удалить из `ProcessMonitor` метрик-агрегацию из heartbeat (`_publish_process_aggregate` + публикацию `workers.X.effective_hz`/`state.fps`/`state.latency_ms` из `_on_heartbeat_received`), т.к. теперь публикует сам процесс. heartbeat оставить ТОЛЬКО для liveness (`_last_heartbeat`, timeout→UNRESPONSIVE) и paused/running.
**Файлы:** `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` (откатить метрик-часть `7f81383a`, оставить liveness). ADR-PMM-009 — обновить (агрегат уехал в процесс).
**Acceptance:** [ ] FPS по-прежнему виден (из Task 1); [ ] нет дублей публикации `state.fps`; [ ] тесты зелёные.

### Task 3 — system.health.active/avg_fps (тоже self или GUI-side)
**Level:** Middle+ **Assignee:** developer
**Goal:** `system.health.active` (число running) / `avg_fps` — посчитать там, где данные уже есть БЕЗ нового посредника. Вариант A: GUI считает из `processes.*.state.status`/`fps` (у GUI всё в кэше после self-publish). Вариант B: ProcessMonitor monitoring-loop (он знает статусы процессов, как для uptime — этот loop РАБОТАЕТ).
**Acceptance:** [ ] qt-mcp: «Активно: N» (N>0), «Средний FPS: <число>».

---

## КРИТИЧНО для исполнителя: дисциплина окружения (иначе утонешь, как сессия 2026-06-04)

- **НЕ убивать приложение через `TaskStop`/kill лаунчера** — это оставляет orphan-дерево дочерних процессов (Windows spawn), которые держат webcam/SHM/порт 9142 и ломают следующий запуск. **Закрывать ТОЛЬКО через окно** (qt-mcp `qt_invoke_slot(MainWindow, "close")`) — штатный `system_stop_event` гасит всё дерево чисто (проверено: exit 0). См. memory `feedback_no_global_taskkill`.
- **Один инстанс за раз.** Перед запуском проверить `netstat 9142` свободен. Если висят orphans — убить ПОФИДНО (`taskkill /PID <pid> /F`, MSYS_NO_PATHCONV=1), не глобально. Найти app-деревья: `wmic process where "name='python.exe'" get ProcessId,CommandLine /format:csv | grep cpython-3.12.12 | grep spawn_main` → группы по `parent_pid` с ≥3 детьми = app-система.
- **Логи ОБЩИЕ между запусками** (`logs/ProcessManager/*.log` дописываются) — фильтровать по сегодняшней дате/времени, иначе читаешь старый run.
- **qt-mcp probe:** `QT_MCP_PROBE=1 python -u multiprocess_prototype/run.py` (НЕ через `&` в фоновом bash — детач умирает с родителем; запускать `run_in_background: true` отдельным таском). probe слушает `127.0.0.1:9142`.
- **Диагностика рантайма:** временный `self.process._log_info("[TAG] ...")` (процессный логгер ПИШЕТ в файл; логгеры отдельных объектов StateStore/Dispatcher — нет, дают ложный «0», см. memory `project_telemetry_subscription_bug`). Читать из `logs/ProcessManager/messages.log`+`system.log`. Убрать диагностику после.
- **Python:** `.venv` = uv cpython-3.12.12 (`requires-python >=3.12,<3.13`). Терминальный `python` = `.venv` (тесты на нём). run.py venv-guard форсит `.venv` при запуске. «cpython» в путях = тот же Python, имя сборки uv.
- **Приёмка ТОЛЬКО qt-mcp live** (pytest-qt/integration НЕ доказывают — в этой сессии integration-тест агента проходил, а живьём FPS=0). memory `feedback_qt_mcp_smoke_verification`.
- **Коммиты:** Conventional + trailers `Why:`/`Layer:` на ОДНОЙ строке; ruff-format переформатирует → re-stage + re-commit; `Refs: plans/telemetry-self-publish-redesign.md`.

## Открытый вопрос Task 1 (решить первым делом)

Есть ли у backend-процессов (camera_0/detector/painter — GenericProcess) рабочий `state_proxy` для записи в дерево? GUI имеет `GuiStateProxy`. Проверить `ProcessModule._init_state_proxy`/ADR-SS-006. Если backend-процессы пишут в дерево только косвенно (через PM) — добавить им прямой `StateProxy(server_target="ProcessManager")`. Это и есть «рабочий поток коммуникации», на который указывал владелец.
