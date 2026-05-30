---
name: Processes workers runtime feature
description: Вкладка «Процессы» — насыщенные карточки + CRUD воркеров (config-персист + live IPC спавн). Ветка feat/processes-workers-runtime.
metadata:
  type: project
---

Фича `processes-workers-runtime` (ветка `feat/processes-workers-runtime`, 2026-05-30, план `plans/processes-workers-runtime.md`). Воркеры стали конфигурируемыми сущностями с реальным runtime-спавном.

**Что сделано (6 фаз, ~12 коммитов, 100+ тестов):**
- **Domain (A):** `WorkerSpec(SchemaBase, frozen)` — worker_name/priority(SYSTEM..BACKGROUND)/execution_mode(loop|task)/target_interval_ms/worker_class/protected/config. `Process.workers: tuple[WorkerSpec,...]`. Файл `multiprocess_prototype/domain/entities/worker.py`.
- **Runtime (B, framework):** `IdleWorker` (`process_module/generic/idle_worker.py`) — generic loop+smart-sleep+`get_cycle_metrics`. Хендлеры `worker.create/remove/update/restart/stop` в `process_module/commands/builtin_commands.py` (рядом с `worker.pause_all`). `WorkerManager`: `remove_worker`, `is_worker_protected` (`PROTECTED_WORKER_NAMES={message_processor}`), `get_worker_status` обогащён priority/protected/cycle-метриками. `ProcessLaunchConfig.workers` → `proc_dict["workers"]` (config-спавн при старте).
- **Bridge/Presenter (C):** `WorkerBridge` (`frontend/bridge/worker_bridge.py`) → `send_command(owner, "worker.*")` ПРЯМО во владельца (не через ProcessManager wrapper). Presenter: `get_workers` (синтетический protected `message_processor` если своих нет), `add/remove/update_worker` (персист `topology.save` + live-IPC), `create/delete_process`.
- **Widgets (D):** `ProcessCard` (ds-card: полоса категории, статус-пилюля, метрики, кнопки-иконки ▶⏸↻🗑) + `WorkerTable` (combo приоритет/режим, spin интервал, protected-guard). qss в `cards.qss` И `main.qss` (sync обязателен — test_style_manifest; токены, не hex — test_no_hardcoded_hex). Файлы `frontend/widgets/tabs/processes/widgets/`.
- **Сборка (E):** SingleProcessPanel = ProcessCard + секция «Воркеры»; CreateProcessDialog/CreateWorkerDialog; tab подписан на `TopologyReplaced` → nav-rebuild ТОЛЬКО при изменении набора процессов (воркер-правки локальны).

**Архитектура спавна:** дефолтный `message_processor` крутится в цикле, опрашивает RouterManager → CommandManager → `worker.*` хендлер → `WorkerManager.create_worker(IdleWorker)`. Воркер сначала idle (no-op), нагрузку даёт Pipeline позже. Двойного спавна нет: live-IPC при GUI-действии, config-спавн при init процесса.

**Qt-smoke verified (probe localhost:9142, QT_MCP_PROBE=1):** ProcessCard+WorkerTable рендерятся; protected `gui` — нет stop/delete + combo disabled; `camera_0` — все 4 кнопки; логи живых процессов показывают `worker.create/remove/... registered successfully`.

**Долги (оба → новый чат с /plan, решение владельца 2026-05-30):**

**Долг #1 — live-телеметрия GUI (АРХИТЕКТУРНЫЙ, не контейнерный!).** На прямой проверке кода: GUI live-телеметрия процессов **вообще не подключена (dormant)**, не только воркеры:
- `process_state_path()` (`backend/state/schema.py:114`) — НЕТ вызовов-сеттеров; ключи `processes.X.state.*` backend не публикует.
- `DataReceiverBridge.dispatch` (`frontend/bridge_impl.py:45-54`) классифицирует «state» только для `status/state_changed/fps_update`; `state_delta` уходит в «command» (не к bindings).
- `GuiStateBindings._on_state_msg` (`frontend/state/bindings.py:172`) игнорирует всё кроме `data_type=="state_delta"`.
- Отсюда статичные «FPS —»/«Активно: 0» в живом приложении.
Задача = построить весь пайплайн: backend-publisher (state_proxy `processes.X.state.*` И `processes.X.workers.Y.*`) → IPC-роутинг → фикс dispatch (`state_delta`→state) → fan-out из heartbeat `workers_status` (несётся: process_heartbeat.py:83 → ProcessMonitor `_workers_status` → broadcast). `WorkerManager.get_worker_status` уже отдаёт priority/status/cycle_duration_ms/effective_hz. Bindings воркеров уже подключены forward-compatible (`_panels.py._bind_worker_telemetry`) — оживут, когда появятся ключи.

**Долг #2 — runtime по `assigned_worker`.** Pipeline персистит `assigned_worker` в config плагина (`MoveWorkerCombo` → field_changed → SetPluginConfig), но рантайм назначает воркеры авто (source→source_producer, processing→pipeline_executor в GenericProcess). Нужно: GenericProcess читает `config["assigned_worker"]` и кладёт плагин в указанный воркер. Это Phase C в `plans/pipeline-node-process-worker.md`.

**Pipeline-селектор воркера (DONE, e44017e8):** в инспекторе Pipeline строка «Процесс / Воркер» — два combo на одной строке (`MoveProcessCombo` + `MoveWorkerCombo`). Воркер-combo из топологии (Process.workers + message_processor); выбор → `field_changed("assigned_worker")` → SetPluginConfig (persist в config плагина). Runtime-исполнение по assigned_worker — следующий шаг.

Связано: [[project_workers_architecture]], [[project_worker_cycle_timing]], [[project_processes_tab]], [[feedback_dict_at_boundary_gui]], [[feedback_qt_mcp_smoke_verification]].
