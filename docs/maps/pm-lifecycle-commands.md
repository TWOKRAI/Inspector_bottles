# Опись команд и писателей PM (Task 1.9b, шаг 0, I2)

> Код — ветка `feat/lifecycle-pm-keyed-executor` на `ee3174515` (= `main` после 1.9a `6c4fc762e` + план). Строки
> выведены `sed -n`/`git grep -n` на этом коммите. `PMP` = `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`,
> `BC` = `multiprocess_framework/modules/process_module/commands/builtin_commands.py`, `MON` = `.../process_manager_module/monitor/process_monitor.py`.
> Классы — D2 из [`T1.9b.md`](../../plans/lifecycle-stop-ownership/tasks/T1.9b.md): **L** — всегда `_lifecycle_executor`;
> **T** — исполнитель, только если цель в переходе / идёт операция L; **R** — сразу, на приёмном потоке (не ждёт другой
> процесс); **S** — `system.shutdown`. «Поток сейчас» для команд — `message_processor` (обе двери: прямая —
> `RouterManager._dispatch_command`, `router_manager.py:1323`; вложенная — `process.command`, `PMP:3292`).
> Полный разбор — [`docs/reviews/2026-10-21_task-1.9b-teamlead-step0.md`](../reviews/2026-10-21_task-1.9b-teamlead-step0.md).

## а) Команды и писатели

Регистрация: встроенные PM — словарь `PMP:486-529`, цикл `register_command` `PMP:531-537`; `process.command` — `PMP:289`.

### Класс L (8)

| Команда | Обработчик | Читает / пишет | Ждёт другой процесс | Расхождение с D2 |
|---|---|---|---|---|
| `process.create` | `PMP:586` → `create_process` `PMP:3632` | пишет реестр (`create_and_register` `:3647`), `_process_configs` `:3651`; при `auto_start` — `process.start()` `:616`, `_instance_started_at` (`_mark_instance_started` `:1459-1464`), `apply_priority` (сон 0,1 с, `core/process_priority.py:144`) | да при `auto_start`: спавн + сон приоритета | нет |
| `process.start` | `PMP:627` → `start_process` `PMP:3664` | реестр (чтение), `process.start()` `:3682`, `_instance_started_at`, приоритет `:3684`; шов наблюдаемости → `_run_when_child_ready` `:1745` | да: спавн + сон 0,1 с | нет |
| `process.stop` | `PMP:634` → `stop_process` `PMP:3722` | реестр: `stop_one` `:3736` → `ChildProcessStop.join_until` (до `stop_process_timeout` + 2,0 с) | да: смерть ребёнка | нет |
| `process.restart` | `PMP:655` → `restart_process` `PMP:3741` | `_process_configs` (чтение `:3753`), реестр (stop `:3758`, `remove_process` `:3760`, `create_and_register` `:3787`), провода (`_mark_wires_broken_for` `:3766`, `_reissue_wires_for` `:3817`), очереди PSR (`register_process` `:3772`, дренаж `:3774`), `_incarnations` `:3784`, `_instance_restarts` `:3802`, `_routing_epoch` `:3820`, журнал телеметрии (доигрывание `:3828`) | да: смерть + спавн + `_wait_processes_ready` `:3811` | нет |
| `topology.apply` | `PMP:795` → `apply_topology` `PMP:3907` | всё: `_process_configs`, реестр, `_incarnations` (`_topology_provision` `:4331`), провода `:4002`, журнал телеметрии `:4058`, сессии наблюдаемости `:4070`, `_replace_in_progress` `:3936`, монитор (пауза `:3957`) | да: `_topology_stop_all` → `stop_many` `:4292`, спавн, `_wait_started_ready` `:3996` | нет |
| `wire.setup` | `PMP:989` | пишет `_active_wires` (`:1040`, `:1083`), SHM; отправляет `wire.configure` источнику и цели (`send_message` `:1067`, `:1079`) | **нет** (fire-and-forget) | нет по классу; довод L — порядок относительно рестарта (переигрывание проводов), не ожидание |
| `wire.teardown` | `PMP:1087` | пишет `_active_wires` (`pop` `:1124`), шлёт `wire.deconfigure` `:1119` | **нет** | то же, что `wire.setup` |
| `recipe.activate` | регистрация `multiprocess_prototype/orchestrator.py:79` (цикл по `service.handlers()`); тело `multiprocess_framework/modules/recipe/service.py:348` | зовёт `_cmd_topology_apply` прямым вызовом `recipe/service.py:356`, пишет манифест | да — через `topology.apply` | нет. Путь `recipe/service.py` — во фреймворке, не в прототипе (D2 верен) |

### Класс T (6 по D2 + 1 кандидат)

| Команда | Обработчик | Читает / пишет | Ждёт другой процесс | Расхождение с D2 |
|---|---|---|---|---|
| `process.relay` | `PMP:3068` | читает PSR (`get_process_data` `:3096`), `send_message` в цель `:3103` | нет | нет (гонка investigator: цель в рестарте — `_drain_process_queues` `:3774` съест билет) |
| `process.pause` | `PMP:641` → `_send_worker_command` `PMP:3832` | читает реестр, `is_alive`, шлёт `worker.pause_all` | нет | нет |
| `process.resume` | `PMP:648` → `PMP:3832` | то же, `worker.resume_all` | нет | нет |
| `telemetry.broadcast` | `PMP:3124` | пишет журнал телеметрии (`_record_telemetry_delta` `:3256`, сброс `:3251`); central-троттл; `_broadcast_command` `:3212` → досылка неготовым → `_run_when_child_ready` `:2805` | нет | нет |
| `observability.tail.subscribe_all` | `PMP:2952` | пишет намерения брокера; рассылка через `_broadcast_command` (`:2867`) | нет | нет |
| `observability.tail.unsubscribe_all` | `PMP:2975` | то же | нет | нет |
| `router.relay` (BuiltinCommands, есть и в PM) | регистрация `BC:3888`, тело `BC:3898` | `router.send_async`/`send` билета с `targets` | нет | **да: D2 не называет.** Тот же класс гонки, что `process.relay`: билет цели в рестарте ляжет в переиспользуемую очередь. Кандидат в T (`targets` — список; ключ — множество целей). Шлёт ли кто-то `router.relay` именно в PM — не проверено |

### Класс S (1)

| Команда | Обработчик | Что делает | Расхождение |
|---|---|---|---|
| `system.shutdown` | `PMP:669` | `set_force_deadline` у `_children_stop` `:709`; `system_stop_event.set()` `:720`, `stop_event.set()` `:721` | нет. Строки D2 «:666-681» устарели — теперь `:669-722` |

### Класс R — сразу, на приёмном потоке

| Команда / группа | Регистрация · обработчик | Что читает / пишет | Ждёт другой процесс | Расхождение с D2 |
|---|---|---|---|---|
| `process.list` | `PMP:573` | монитор `broadcast_full_status` (читает реестр) | нет | нет |
| `process.status` | `PMP:662` → `PMP:3861` | реестр, PSR | нет | нет |
| `system.stats` | `PMP:724` | монитор, `_status.get_all_status()` (реестр) | нет | нет |
| `supervision.status` | `PMP:735` | `_routing_lock` → `_routing_epoch`/`_incarnations` `:755-757`; без лока — `_instance_restarts`, `_instance_started_at`, реестр | нет | нет |
| `topology.get` / `topology.diff` | `PMP:967` / `PMP:976` | `_process_configs`, менеджер топологии | нет | нет |
| `wire.status` | `PMP:1128` | итерирует `_active_wires` `:1134` без лока | нет | нет |
| `process.command` (дверь) | `PMP:289` (CM, `manages_own_reply=True`), запасной `PMP:297`; тело `PMP:3292` | строит `inner_msg` заново `:3332`, `handle_command(inner_msg)` `:3338` — без `reply` | как вложенная команда | нет (это дверь, не класс) |
| `recipe.list/get/save/validate/delete` | `multiprocess_prototype/orchestrator.py:79`; тела `recipe/service.py:291/301/308/333/366` | файлы рецептов под `self._lock(name)` | нет | нет |
| `service.list/status/start/stop/restart` | `multiprocess_prototype/orchestrator.py:103`; тела `service_module/host.py:99/112/131/156/185` | состояние `ServiceHost`; `start` ждёт `job.done.wait(_start_wait_sec)` `host.py:150`; `stop` — синхронный `instance.stop()` `host.py:176` | **внутрипроцессное ожидание** (не другой процесс) | **да по имени:** D2 зовёт их «чтение», а `start/stop/restart` — писатели и стоят на приёмном потоке. По критерию D2 («ждёт другой процесс») — R. Вне объёма 1.9b (полоса Services, handoff п.2) |
| `state.set/merge/delete/get/get_subtree/subscribe/unsubscribe/unsubscribe_all` | `state_store_module/manager/state_store_manager.py:636` (из `app_module/orchestrator.py:450`, только прикладной PM) | дерево состояния SSM (свой лок SSM — не проверен) | нет | нет |
| BuiltinCommands в PM, кроме `router.relay`: `worker.*` (9), `introspect.*` (10), `catalog.plugins`, `config.reload`, `telemetry.reconfigure`, `observability.sink.*`/`logger.sink.*` (6), `log.tail.subscribe/unsubscribe`, `observability.persist`, `observability.tail.subscribe/unsubscribe`, `health.report/status`, `diag.thread_raise/warn`, `wire.configure/deconfigure`, `routing.probe/refresh` | `BC:331`, `:337`, `:377`, `:708`, `:725`, `:1778`, `:3502`, `:3516`, `:3696`, `:3702`, `:3942`, `:3948` | свои менеджеры PM | нет; `diag.thread_raise` ждёт свой поток `BC:3623` (внутри процесса) | **да: D2 называет только `introspect.*`** — остальные 31 имя не названы; по критерию — R |
| `heartbeat` (обработчик роутера, не CM) | `MON:247`, тело `MON:254` | пишет `_last_heartbeat`/статус монитора | нет | нет |
| `state.changed` (обработчик роутера) | `process_module/core/process_module.py:941` (если есть `state_proxy`) | прокси состояния | нет | нет; есть ли `state_proxy` у PM — не проверено |

### Не-командные писатели

| Писатель | Где | Поток | Что пишет / читает | После 1.9b |
|---|---|---|---|---|
| Монитор: авто-рестарт | `_dispatch_due_restarts` `MON:1475`, отправка `MON:1511` | поток монитора | шлёт `process.restart` в свою очередь PM (IPC, не прямой вызов) | команда уходит в `_lifecycle_executor` — сериализация с `topology.apply` сохраняется исполнителем; докстринг `MON:1476-1481` устареет (файл 4 FILES) |
| Монитор: чтение | `_active_wires` `MON:645`; `_process_configs` `MON:1111`, `:1201`, `:1626` | поток монитора | читает словари PM «живьём», без лока | писатель переезжает с `message_processor` на исполнитель — гонка та же, что сегодня; D3-лок должен покрыть и эти чтения |
| Монитор: `forget_process` | `MON:1576` (зовёт очистка топологии) | поток вызывающего (L) | словари монитора | исполнитель |
| `ready-gate-<имя>` | `PMP:1602-1607` → `_drain_child_actions` `PMP:1610` | daemon-поток на адресата | шлёт отложенные команды ребёнку | `_ready_gate_executor` (D5) |
| backend_ctl: `_note_point_request` | `PMP:2877` (колбэк `on_request`, `PMP:316`) | поток чтения сокета | словарь точечных намерений брокера | без изменений |
| backend_ctl: `_forget_closed_session` | `PMP:2912` (колбэк `on_session_closed`, `PMP:312`) | поток чтения сокета | намерения брокера и подписки SSM; адресные `unsubscribe` — `_send_point_unsubscribe` `observability_broker.py:243` (без ready-gate) | без изменений |
| Watcher наблюдаемости `GenericProcessManagerApp` | `_fan_out` → `_broadcast_command("config.reload")` `app_module/orchestrator.py:282` | поток watcher'а | рассылка детям + досылка неготовым → `_run_when_child_ready` `PMP:2805` | ядро гейта — исполнитель готовности |
| Watcher спутника рецепта | `app_module/orchestrator.py:241` (`on_reload_extra` → `_compose_fan_out`) | поток watcher'а | то же | то же |
| Boot | `_create_processes_from_config` `PMP:3402`, `_wait_boot_ready` `PMP:4203` | поток `initialize()` | реестр, `_process_configs` | вне объёма (до приёма команд) |

## б) Вызовы `_run_when_child_ready` (`PMP:1540`)

| Откуда | Цепочка | Поток сейчас | Поток после 1.9b |
|---|---|---|---|
| `PMP:1241` (`_reissue_wires_for`) | `restart_process` `:3817`; `apply_topology` `:4002` | `message_processor` | `_lifecycle_executor` (гейт — на месте, если ребёнок готов) |
| `PMP:1745` (`_replay_observability_when_ready`) | `_mark_instance_started` `:1464` ← `start_process` `:3683`/`:3697`, `restart_process` `:3792`, `_cmd_process_create` `:617` | `message_processor`; boot — поток `initialize()` | `_lifecycle_executor`; boot — без изменений |
| `PMP:2347`, `PMP:2398` (`_replay_telemetry_runtime_delta`) | `restart_process` `:3828`; `apply_topology` `:4058` | `message_processor` | `_lifecycle_executor` |
| `PMP:2805` (`_redeliver_to_unready_children`) | `_broadcast_command` `:2651` ← `routing.refresh` `:2064` (L), `telemetry.broadcast` `:3212` (T), брокер `:2867` (T), сброс сессий `:2577` (из `apply_topology` `:4070`), телеметрия `:2379` (L) | `message_processor` | L — исполнитель; T — `message_processor` или исполнитель |
| `app_module/orchestrator.py:282` → `PMP:2805` | watcher `config.reload` | поток watcher'а | без изменений |

Отложенная часть сейчас всегда идёт на `ready-gate-<имя>` (`PMP:1602`); после 1.9b — рабочий `_ready_gate_executor`.

## в) Вопросы стадии 0

Доказательства и рассуждения — в отчёте. Здесь только позиция.

- **(а)** Пул фиксирован в конструкторе (`keyed_executor.py:145-152`). Ожидающее действие занимает рабочего до `deadline_s`
  (30 с наблюдаемость `PMP:1749`, 15 с переигрывание проводов `PMP:1245`). Сегодня поток на адресата без верхней границы `PMP:1602`.
  Позиция: `max_workers` — явный ключ конфига PM `ready_gate_max_workers`, умолчание 16 (×2 к оценке «8 процессов»
  ADR-WRK-005). Проверка после каждого `topology.apply`: живых детей больше пула — один WARNING. Перегрузка даёт задержку
  доставки, не потерю: срок действия считается от его старта (`PMP:1656`). Цена — 16 простаивающих рабочих, каждый
  просыпается 10 раз/с (`_WAIT_S=0.1`, `keyed_executor.py:61`). Решение по умолчанию — за лидом.
- **(б)** Ломается так: решение «готов» (`PMP:1590`) снято вне лока исполнителя. Между проверкой и исполнением на месте
  рестарт может подменить `ready_event`. Ждущее действие перечитает событие (`PMP:1685-1691`) и будет ждать до срока на
  вызывающем потоке: `message_processor` для T-команд, поток watcher'а. Позиция: при `inline_if_idle=True` подавать
  обёртку, которая на вызывающем потоке зовёт голое `action` (как сегодня `PMP:1599`), а на рабочем — ждущее. Признак —
  `threading.get_ident()` вызывающего, снятый до `submit`. Неготовый ребёнок — `inline_if_idle=False`.
- **(в)** Раскладка `_ChildrenStop.request_stop()`. (1) `try:` — PM-флаг «стоп детей» `.set()`,
  `executor.request_stop()` (не блокирует), `executor.join_until(d)`, где `d = now + infra_s`. (2) `finally:` — нынешний
  `_start()` с паузой монитора со сроком `max(0, d − now)`, затем `group.request_stop()`. Так стоп детей идёт всегда, и
  один срок `infra_s` на оба ожидания не удваивает блокировку фазы 1 (прецедент — монитор `PMP:4382-4384`, `:4414`).
  `should_abort`/`should_reject` = `system_stop_event.is_set() or флаг`: PM гасится и без `system_stop_event`
  (`runner/process_runner.py:192-196`, только `stop_event`). С потока самого исполнителя — только `request_stop`, без
  `join_until`. `_stop_children_once` из D4 в коде нет (снят в 1.2a): путь один — корень.
- **(г)** Нет. Обработчики L не меняют `data`: `_merge_cmd_args` пишет в `kwargs` (`PMP:51-55`), `create`/`relay` —
  `kwargs.update(data)` (`:599`, `:3089`); вложенная дверь строит `inner_msg` заново (`:3332`). Не проверено:
  `apply_topology(td)` и `TopologyManager` — меняют ли они `td`, вложенный в `data`.
- **(д)** `_routing_lock` (`PMP:112`, `threading.Lock`, не `RLock`): `:755`, `:1971`, `:1999`, `:2013`, `:2051`. Других
  локов на словари D3 нет: `_process_configs`, `_active_wires`, `_instance_*` и журнал телеметрии (`:2072-2175`) — без
  лока. `_child_action_lock` (`:1533`) и лок поколений (`:2729`) — про другое.
- **(е)** Правка `_own_work` не нужна. Рабочие `KeyedExecutor` — SYSTEM-воркеры `WorkerManager` (`keyed_executor.py:147-152`).
  Их уже закрывает запись `work/workers` (`process_module.py:278`, `_WorkersStop.join_until` →
  `stop_all_workers`, `process_lifecycle.py:192-196`). Порядок «исполнитель → дети» держит вызов внутри
  `_ChildrenStop.request_stop()`: фаза 1 сегмента `work` идёт до LIFO-фазы 2 (`app_module/orchestrator.py:91-93`).
  Создавать в `initialize()` после `super().initialize()` — `worker_manager` уже есть.
- **(ж)** Не в D2: `router.relay` (кандидат T); 31 имя BuiltinCommands (R); `service.start/stop/restart` — писатели, а не
  «чтение». В D2 по ошибке: ADR-PMM-038 уже занят (`process_manager_module/DECISIONS.md:1813`, `system.shutdown mode=force`)
  — новому ADR нужен свободный номер, `ADR-PMM-039` в коде и ADR не занят, его как кандидата называет `T1.10.md:29`; строки D2 `:666-681`, `:3251-3331`, `:3297`, `:3539`, `:4065-4123`,
  `:4338` сдвинулись — теперь `:669-722`, `:3292-3372`, `:3338`, `:3580`, `:4106-4164`, `:4423`. Стоп на приёмном потоке,
  который вынос не покроет: другого не найдено. Единственный вызов `handle_command` без `reply` в PM — `PMP:3338`, и его
  D2 переводит на `reply`.
