# Срез F — сверка цепочки с graphify и диаграммами (haiku, 2026-10-13)

Сырой отчёт агента. Только чтение.

## 1. Рёбра
| # | Ребро | В графе? | В диаграммах? | Примечание |
|---|---|---|---|---|
| 1 | `RecipesTab._on_activate_clicked` (tab.py:457) | да, строка совпадает | нет | кнопка «Загрузить» (tab.py:118, 261); docstring tab.py:8, :257 — «Сделать активным» |
| 2 | `on_set_active` (presenter.py:316) → `store.set_active` (recipe_store.py:133), dispatch `ActivateRecipe` (presenter.py:390, commands.py:206) | да, ребро calls L390 | нет | — |
| 3 | presenter → `device_sync_set` | частично | нет | presenter.py:407-418 `upsert_devices_fn` → tab.py `_build_upsert_devices_fn` (~421-427) → `send_action_command` → `_route_command` (command_sender.py:97) → `process.relay` (:110) → PM `_cmd_process_relay` (:3024, рег. :504); IPC-хоп в графе не виден; `device_sync_set` рег. plugin.py:92, def :562 |
| 4 | `ProcessManagerProxy.apply_topology` (:73) → `_dispatch_async` (:154) → `RequestRunner.submit` (request_runner.py:90) → `request_system_command` (command_sender.py:253) | код есть | нет | — |
| 5 | RouterManager → CommandManager → `_cmd_topology_apply` (:751) | узел да | нет | рег. `topology.apply` :498 |
| 6 | `_topology_debounce_reject` (:798), `_retarget_recipe_address` (:845) | да, рёбра L767, L780 | нет | — |
| 7 | `_cmd_topology_apply` → прототип `apply_topology` | частично | нет | override `orchestrator.py:50-52` → `orchestrator_hooks.py:223`; явного ребра нет |
| 8 | `apply_topology` (:3842) → `TopologyManager.apply` (topology_manager.py:163) → planner | узлы да | нет | `FullReplacePlanner` planner.py:136, `.commands()` :216, `_detect_protected_conflicts` :305; `_build_proc_dicts` orchestrator_hooks.py:122; `BlueprintAssembler` assembler.py:52 |
| 9 | `_topology_stop_all` :4212, `_cleanup` :4236, `_provision` :4252, `_create` :4282, `_start` :4301, `_execute_command` topology_manager.py:311, `stop_many` process_registry.py:350, `apply_priority` process_priority.py:131, `start_process` :3620 | да | нет | — |
| 10 | `_wait_started_ready` :4162, `_wait_processes_ready` :4041, `_voice_liveness_fallback` :4107, `_rollback_to_snapshot` :1801, `_refresh_after_topology` :2967, `_resume_monitor` :1895, `_replay_telemetry_runtime_delta` :2244, `_reset_observability_sessions` :2432 | да | нет | — |
| 11 | `RouterManager.reply_to_request` (router_manager.py:1250) | да | нет | — |
| BE | `RecipeService.activate` (recipe/service.py:348), рег. :122 | да | нет | вызовов вне тестов нет |
| CS | `SystemBuilder.from_manifest` | два класса: backend/launch.py:477 (:512) и app_module/builder.py:294 | нет | `merge_topologies` launch.py:148 против `_merge_topologies` app_module/builder.py:534 |
| LOG | `ConsoleChannel` (log_channel.py:1043) → `_guarded_write` (:179) | да | нет | — |

Замечание: короткие метки в graphify резолвятся в чужие узлы (README, rationale, протокольный стаб) — нужны полные метки.

## 2. Рёбра вне цепочки
- Прямой вызывающий `PM.apply_topology` один — `_cmd_topology_apply` :786; протокол interfaces.py:202; override prototype orchestrator.py:50; тесты.
- **Второй GUI-путь:** `TopologyBridge` (topology_bridge.py:382-442) и `apply_topology_diff` (:518) из `actions_module/handlers/topology_handler.py:31,78` (undo/redo) — живость не проверена.
- Отправитель `device_sync_set` в прототипе — только tab.py.
- Манифест: `ManifestStore.set_pipeline` (app_module/store.py:121); читатели app_module/builder.py:312, orchestrator.py:368. `recipe/DECISIONS.md:447` говорит, что `recipe.activate` зовёт `set_pipeline` — прямого вызова в service.py нет.
- `process.hot_add` — билдер `frontend_module/bridge/system_commands.py:77`, в реестре PM нет.

## 3. Диаграммы и устаревший текст
- Диаграмм смены/активации нет в `docs/diagrams/` и `multiprocess_framework/docs/DIAGRAMS.md` (там жизненный цикл процесса, :84-95).
- `replace_blueprint` (снят): `multiprocess_framework/DECISIONS.md:154, 2224-2233`; `docs/COMMUNICATION_MAP.md:38,161,215,235`; `docs/COMMUNICATION_ARCHITECTURE.md:47,199`; `frontend_module/DECISIONS.md:101`; `process_manager_module/DECISIONS.md:448,486,692`; `Plugins/hub/device_hub/DECISIONS.md:19`.
- «Сделать активным»: `recipes/tab.py:8, 257`, `presenter.py:317`.

## 4. Свежесть
`graphify-out/graph.json` 2026-10-13 09:31, 40 866 узлов, 65 755 рёбер, 2 292 сообщества; проверенные строки совпали с кодом.

## Что осталось открытым
`run.py`/`main.main` в графе; ребро `apply_topology → TopologyManager.apply`; какой `SystemBuilder` участвует в холодном старте; живость `TopologyBridge`; `_persist_active_fn` в tab.py мимо `ManifestStore`; `process.hot_add` в реестре PM.
