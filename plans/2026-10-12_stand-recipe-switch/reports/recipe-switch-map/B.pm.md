# Срез B — `topology.apply` в ProcessManager (Explore/haiku, 2026-10-13)

Сырой отчёт агента-разведчика для схемы `docs/maps/recipe-switch.md`. Ссылки сверены агентом чтением файлов.

## Ответ
Один путь на потоке `ProcessManager_message_processor`: команда → debounce → ретаргет адреса рецепта → обёртка DisplayRegistry → `PM.apply_topology` (snapshot, стоп монитора) → `TopologyManager.apply` (5 фаз: stop_all → cleanup → provision → create → start) → при провале best-effort rollback без 2PC → барьер готовности (окно 0.5 с, фолбэк по живости) → ответ. Protected не трогаются; конфликт их конфига только репортится, apply не прерывается. Ответ уходит после всей работы; всё это время прочие системные команды PM не обрабатываются.

**Поправки номеров строк:** `TopologyManager.apply` def :163 (:213 — цикл команд); `_execute_command` def :311 (:400 — ветка `process.create`); `_topology_create` def :4282 (:4296 — вызов `apply_priority`); `apply_priority` def :131 (:144 — `time.sleep`); ERROR планировщика `planner.py:340-342` (не ~282); обработчик `_cmd_topology_apply` начинается на :751 (:780 — ретаргет).

## 1. Шаги
1. `process_manager_process.py:751-796` `_cmd_topology_apply`: `topology_dict` обязателен (758-760).
2. `:767` debounce; `:798-824` `_topology_debounce_reject`: `_replace_in_progress` (807), cooldown `replace_debounce_s` (815; 1.0 в `launch.py:759`).
3. `:780` `_retarget_recipe_address` (`:845-875` → `app_module/orchestrator.py:289-320`; при пустом `recipe_path` `:301-302` читает манифест — файловый IO). При провале адрес откатывается (`:794-795`).
4. `:786` `self.apply_topology(td)` → override `prototype/orchestrator.py:50-52` → `orchestrator_hooks.py:223-277`: `DisplayRegistry.reload` ДО apply (`:265`), `super_apply` (`:268`), откат display только при `rolled_back` (`:271`).
5. `:3842-4036` `apply_topology`: повторный debounce (`:3861`), `_replace_in_progress=True` (`:3871`), snapshot = deepcopy non-protected конфигов (`:3878`, `:3818-3826`), wires broken (`:3884-3886`), `ProcessMonitor.stop()` без явного таймаута (`:3892`).
6. `:3897` `TopologyManager.apply`.
7. `:3931` `_wait_started_ready`; `:3935-3937` reissue wires; `:3971-3984` protected conflicts; `:3988` `_refresh_after_topology`; `:3993` `_replay_telemetry_runtime_delta`; `:4005` `_reset_observability_sessions`.
8. `:4035` `_resume_monitor`; `:4037-4039` сброс флага, `_last_replace_ts`.

## 2. Diff / план
- `topology_manager.py:192` → `planner.diff` всегда `has_changes: True` (`planner.py:197-214`) — сравнения old/new нет.
- `planner.py:241` сборка и валидация proc_dicts первыми (`BlueprintInvalid` → ни одной stop-команды).
- Old = `_process_configs` минус protected (`process_manager_process.py:3828-3836`, `planner.py:252`). **Все non-protected сносятся, даже если конфиг не менялся** (FullReplace).
- Protected = PM + процессы с `"protected": True` (`process_manager_process.py:1228-1238`); не стопятся и не пересоздаются (`planner.py:260`).
- Конфликт protected (`planner.py:305-344`): сравнивается полный `proc_dict` после канонизации плагинов (`:87-133`) — все ключи, включая лог-пути.
- Конфликт не прерывает apply: процесс остаётся со СТАРЫМ конфигом; в ответе `protected_conflicts` (`process_manager_process.py:3971-3973`), `report_error` (`:3977-3984`), ERROR (`planner.py:340-342`).
- Процесс, ставший protected только в новом рецепте, создаётся как обычный (`planner.py:248-250`).

## 3. Стоп
- Команды (`planner.py:265-295`): одна `process.stop_all` (`:267`), `process.cleanup` по каждому старому (`:270-271`), затем provision, create, start.
- `_topology_stop_all` (`process_manager_process.py:4212-4234`) → `registry.stop_many(names, stop_process_timeout or 5.0)`; параллельно: `process_registry.py:441-471` → `open_scope` (budget = timeout, reserve = KILL_RESERVE_S), `ChildProcessStop` (`child_process_stop.py:44`). Фазы (`stop_budget.py:35-49`): stop_event → graceful до 5.0 с → terminate → 1.0 с → kill → 1.0 с; опрос 0.05 с.
- Неподтверждённый стоп → `_publish_unstoppable_alert` (`:4232`), `return False` → hard-fail, rollback.
- `_topology_cleanup` (`:4236-4250`) best-effort.

## 4. Старт и готовность
- `_topology_start` (`:4301-4311`) → `start_process` (`:3620-3641`): `process.start()` + `apply_priority` (`:3640`).
- `apply_priority` — `time.sleep(0.1)` (`process_priority.py:144`), зовётся и в create (`:4296`), и в start.
- `_wait_started_ready` (`:4162-4196`): `start_ready_timeout_s` = 0.5 по умолчанию (`:4192-4193`).
- `_wait_processes_ready` (`:4041-4099`): опрос 0.05 с; mp.Event (`process_runner.py:443-452`); мёртвый → False; **на дедлайне живой без события → True** (`:4096-4098`).
- `liveness-fallback` (`:4130`): INFO, WARNING при серии > `escalate_after_repeats` (`:4133-4136`).
- Событие шлёт ребёнок в конце `run()` через `_announce_ready` (`process_module.py:1380`, def `:1293-1306`) — мимо IPC.
- Не готов (`:3944-3953`) → `report_error`, но ответ остаётся `success: True`.

## 5. Атомарность
- 2PC нет. `topology_manager.py:212-250`: hard-fail → `success False`, `_current_topology` не коммитится (`:253`).
- PM (`:3899-3928`): есть `results` → `_rollback_to_snapshot` (`:1801-1893`): стоп snapshot + partial_new, неподтверждённые исключаются, cleanup/provision/create/start best-effort; **барьера готовности при откате нет** (`:1888`).
- Пустые `results` (валидация) → без отката, старые не тронуты (`:3906-3914`).
- Исключение (`:4011-4032`) → rollback, bump epoch, broadcast refresh.
- При провале шага K возможна смесь старого и нового; неподтверждённые стопы остаются вне топологии до следующей смены.

## 6. Локи
- `_routing_lock` (`:109`): `_bump_routing_epoch` (`:1955`), `_bump_incarnation` (`:1969`, из provision `:4266`), `_broadcast_routing_refresh` (`:2007`), `_cmd_supervision_status` (`:711`), `:1927`.
- `_child_action_lock` (`:1489-1493`, `:1541`, `:1577`) через `_run_when_child_ready` (`:1496`) — из `_reissue_wires_for` (`:1197`) и replay телеметрии (`:2303`, `:2354`); потоки `ready-gate-<name>` (`:1558-1563`).
- `_replace_in_progress` — без лока, check-and-set не атомарен; безопасно только на одном потоке.
- Не проверены: `_broadcast_generations_lock` (`:2647`), registry `_lock` (`process_registry.py:518`), `ChildProcessStop._lock` (`child_process_stop.py:70`).

## 7. Ответ
- `router_manager.py:1299-1347` `_dispatch_command` → `cm.handle_command` синхронно (`command_manager.py:262`) → `reply_to_request` (`:1345`), адресация по `request_id` (`:1286`); из `receive()` (`:1380-1460`) на потоке message_processor.
- Пока идёт apply — прочие системные команды и heartbeats PM не обрабатываются (`process_manager_process.py:4055-4058`, `DECISIONS.md:126`); ready-события идут мимо.

## 8. Маркеры
TODO/FIXME/FROZEN в `process_manager_process.py`, `topology_manager.py`, `planner.py`, `orchestrator_hooks.py`, `process_priority.py` — нет.

## Что осталось открытым
- Не читались: `ProcessMonitor.stop()` и его таймаут; `_refresh_after_topology` (`:2967`), `_reset_observability_sessions` (`:2432`), `_replay_telemetry_runtime_delta` (`:2244`) — возможные блокировки на IPC в потоке сообщений; `_collect_partial_new` (`:1747`); `BlueprintAssembler` (лог-пути в proc_dict).
- Не проверены все вызывающие `apply_topology` (второй путь вне потока сообщений?), `get_platform_adapter`.
- Возможная гонка: `orchestrator_hooks.py:268-272` восстанавливает DisplayRegistry только при `rolled_back`, а debounce-ответ (`:813`, `:822`) даёт `rolled_back False` — достижимо, если debounce сработает между `:767` и `:3861`. По коду, не воспроизведено.
- Тесты не запускались.
