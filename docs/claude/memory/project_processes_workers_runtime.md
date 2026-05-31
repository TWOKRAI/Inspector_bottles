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

**Долги — статус 2026-05-31 (план [[../../../multiprocess_prototype/plans/processes-workers-runtime-debts]]):**

**Долг #1 — live-телеметрия GUI → ✅ DONE (feat 574017fd, полный StateStore-путь).**
Реализовано: ProcessMonitor публикует `processes.X.state.status` и `processes.X.workers.Y.{status,effective_hz}` в локальный StateStoreManager (`_publish_state`, без IPC) → DeltaDispatcher → GuiProcess стал подписчиком (`GuiStateProxy` + `_StateDeltaEmitter` в main thread, подписка `processes.**`) → `bridge.dispatch(state_delta)` → существующие `GuiStateBindings` ожили. `dispatch` теперь гонит `state_delta`→`kind="state"` (bridge.py+bridge_impl.py).
**Находка-фундамент (U1):** cross-process подписка StateStore в проде была **сломана** — `DeltaDispatcher` слал `state.changed` через `router.send_async` с `targets`, но `RouterManager._resolve_channels` поле `targets` НЕ читает и route для `state.changed` нет → silent drop (зелёными были только тесты через `InMemoryRouter`). Фикс: `RouterManager._deliver_by_targets` — fallback в `_do_send`: если канал не резолвится и есть `targets` → доставка через `queue_registry.send_to_queue(target, qtype, msg)` (qtype `system` для command). `DeltaDispatcher` ставит `queue_type="system"`. 788 тестов + headless-integration `test_integration_u1_delivery.py` доказал путь.
**Вне scope (новый долг):** `processes.X.state.fps`/`latency_ms` (карточки) и `system.health.*` — нет продюсера, останутся «—».

**Долг #2 — runtime по `assigned_worker` → ⏳ PENDING (Фаза 2, вариант A).** Pipeline персистит `assigned_worker`, но рантайм игнорирует (всё в один `pipeline_executor`; WorkerSpec-воркеры стартуют как IdleWorker no-op). Решение владельца: **вариант A** (воркер = параллельная ветвь, группа плагинов; обобщает B). Эпицентр `generic_process.py:_init_data_pipeline`: группировать по assigned_worker, PipelineExecutor на группу + in-process queue handoff + stop/recreate IdleWorker. См. план.

**IPC-архитектура (решение владельца 2026-05-31):** «всё через RouterManager» — подтверждено; `send_message`/`broadcast` и `router.send(targets=...)` теперь сходятся на shared `queue_registry` (адресная книга оркестратора). **Push-модель** (оркестратор рассылает книгу всем + адресация до воркера) — отложена в **отдельный `/plan`** (не из этих долгов).

**Pipeline-селектор воркера (DONE, e44017e8):** в инспекторе Pipeline строка «Процесс / Воркер» — два combo на одной строке (`MoveProcessCombo` + `MoveWorkerCombo`). Воркер-combo из топологии (Process.workers + message_processor); выбор → `field_changed("assigned_worker")` → SetPluginConfig (persist в config плагина). Runtime-исполнение по assigned_worker — следующий шаг.

Связано: [[project_workers_architecture]], [[project_worker_cycle_timing]], [[project_processes_tab]], [[feedback_dict_at_boundary_gui]], [[feedback_qt_mcp_smoke_verification]].
