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

**Долг (follow-up):** live fan-out телеметрии воркеров в GUI — heartbeat несёт `workers_status` (process_heartbeat.py:83 → ProcessMonitor), но GUI-слой не раскладывает в ключи `processes.{proc}.workers.{name}.*`. Bindings в `_panels.py._bind_worker_telemetry` подключены forward-compatible (статус/Гц оживут когда появится fan-out).

**Запрос владельца (2026-05-30, ещё не сделано):** воркеры должны быть в Pipeline рядом с выбором процесса (два селектора на одной строке: процесс + воркер).

Связано: [[project_workers_architecture]], [[project_worker_cycle_timing]], [[project_processes_tab]], [[feedback_dict_at_boundary_gui]], [[feedback_qt_mcp_smoke_verification]].
