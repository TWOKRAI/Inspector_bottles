# Расследование 1.1-INV — три красных приёмочных теста `apps/line_sim` (критерии 3/4/5)

**Дата:** 2026-09-20. **Ветка:** `feat/line-sim`, HEAD `5ccb3afb`. **Роль:** investigator
(чтение + прогоны; дерево не менялось, `git status` чист до и после).
**Вход:** `docs/reviews/2026-09-20_task-1.1-developer.md`, `docs/reviews/2026-09-20_task-1.1-tester.md`.
**План:** `plans/line-sim/phase-1-vertical-slice.md` §Task 1.1.

## 0. Воспроизведение (input → observed output)

```
cd .../worktrees/line-sim && PYTHONPATH=$PWD .venv/bin/python -m pytest \
    apps/line_sim/tests/test_f1_task11_acceptance.py -q --tb=line
```
→ `3 failed, 3 passed in 32.33s`; красные — `test_backend_ctl_sees_robot_and_status`,
`test_job_counts_writes_in_status_and_history`, `test_without_pymodbus_plugin_errors_process_lives`.

Два живых стенда (скрипты в `/private/tmp/claude-501/lsinv/`, в дерево не попали):
* **Прогон A** (`probe.py`) — штатный line_sim + Modbus-задание, дамп
  `introspect.observability` процесса `robot`, дамп SQLite-стора, листинг лог-каталога.
* **Прогон B** (`probe2.py`) — то же, но launcher собран через `AppSpec(state_bootstrap=…)`
  и порт 5021 занят в родителе (плагин обязан `report_error`).

## 1. Главный вывод: корней ТРИ, и ни один не тот, что назван в брифе

| Критерий | Корень | Класс | Где чинить |
|---|---|---|---|
| 3 | нет `StateStoreManager` у generic-оркестратора → нет хендлера `state.get_subtree` | **код фреймворка** | Task 1.0 (`app_module`) |
| 4 | `ctx.record_metric` — счётчик; в сторе он ложится **агрегатом окна с `metric IS NULL`**. Дорога «число с именем» у плагина — другая (`publish_metric`/уровни) | **модель теста + выбор дороги в плагине**, НЕ конфиг и НЕ разница generic/прототип | решение lead/cto, см. §4 |
| 5 | тест читает `<log_dir>/<process>/errors.log`; плоскость ошибок по **документированному** контракту пишет в `<log_dir>/errors.log` — в корень и ОБЩИЙ на все процессы | **неверная модель теста** | Task 1.1 (правка теста) |

Гипотеза разработчика («SQLite-стор тапает только error+logger, stats не тап-источник»)
**верна по букве и неверна по выводу**: stats попадают в стор не тапом, а дренажом hub'а —
измерено, в сторе `robot` лежат stats-строки.

## 2. Критерий 4 — почему `history_query(metric=…)` пуст

### Измерения (прогон A)

`sqlite3` по файлу стора прогона (`observability.db`, 135 168 Б):

```
SELECT kind, process, metric, count(*) FROM records GROUP BY kind, process, metric
{'kind': 'log',   'process': 'ProcessManager', 'metric': None, 'n': 35}
{'kind': 'log',   'process': 'robot',          'metric': None, 'n': 29}
{'kind': 'stats', 'process': 'ProcessManager', 'metric': None, 'n': 2}
{'kind': 'stats', 'process': 'robot',          'metric': None, 'n': 2}
```

То есть **стор, hub и дренаж на generic-дороге работают** — у `robot` есть и log-, и
stats-строки. Пусто ровно одно: колонка `metric`.

`drv.history_query(metric="sim_robot.writes")` → `{"rows": [], "count": 0}`;
`drv.history_query(kind="stats")` → строка
`{"kind":"stats","process":"ProcessManager","metric":null,"message":"metrics snapshot (count=258), имён 10: …","extra":{"aggregate":true,"metrics":[…]}}`.

`introspect.observability` процесса `robot` (прогон A), значащие поля:

```
counters.observation.numbers_delivered       = 201   # ctx.record_metric доехал
counters.observation.channel_written_records = 0
counters.stats.metrics_count                 = 201
counters.stats.channel_written_by_channel    = {log_stats: 1, hub_stats: 1}
observation.writers                          = 0     # уровней не объявлял никто
history.rows                                 = {log: 55, error: 0, stats: 2, observation: 0}
```

### Механизм (якоря)

1. `Plugins/sim/robot_host/plugin.py:193` → `ctx.record_metric("sim_robot.writes", delta)`.
2. `multiprocess_framework/modules/process_module/plugins/base.py:619,604-616` —
   `_stats_call` уводит вызов в **порт наблюдений**, не в hub.
3. `statistics_module/observation/observation_manager.py:442-469 (_route_number)` →
   `:718-830 (_deliver_number)` → `_emit_to_taps` — синхронная раздача CRM-тапам;
   приёмник — `StatsManager`, число становится слагаемым **окна агрегации**.
4. Окно сбрасывается каналами `log_stats` (в логгер) и `hub_stats` (в hub) —
   одной записью `kind=stats`, `aggregate=true`.
5. `channel_routing_module/observability/record_display.py:213-218` говорит это прямым
   текстом: «агрегат окна (`aggregate=true`) → `message` — строка снапшота, **`metric=None`**;
   так выглядят ВСЕ записи живого стенда (замер 2026-08-14)».
6. `channel_routing_module/observability/observability_store.py:783-787` — `metric` это
   **точный** фильтр: «Строки без имени (агрегат окна, лог, ошибка) в такой срез не попадают
   вовсе: у них колонка NULL, а `metric = ?` NULL не равен».

Строки с непустым `metric` рождаются только двумя дорогами
(`channel_routing_module/observability/number_record.py:82-120`,
`process_module/managers/observability_wiring.py:212-220`):
* одиночная сырая stats-запись в hub (`ObservabilityHub.record_metric`, слот `stats`
  у `worker_module`) — `metric` = имя как есть;
* `KIND_OBSERVATION` — уровни порта наблюдений (`ctx.publish_metric`), эмитит heartbeat;
  идентичность = `"<писатель>.<имя>"`, писатель = имя плагина
  (`plugins/base.py:663-675 _metric_writer`).

У `robot` вторая дорога мертва по построению: `observation.writers = 0`,
`gate_active = False`, `evaluated_ticks = 0` — плагин уровней не публикует.

### Посылка брифа про прототип не подтвердилась

`backend_ctl/probes/probe_observability_consumer_acceptance.py:661-675`, строка R12
живого стенда прототипа: *«известное с Task 3.8: у снапшотов metric=NULL; **на
inspection_full записей с metric нет вовсе** (camera_service чисел не пишет)»*.
То есть «у прототипа `history_query(metric=)` отдаёт строки» — не общий факт дороги, а
свойство рецепта, где плагин публикует УРОВНИ (`capture.drops` — писатель `capture`,
имя `drops`). **Ни один ключ секции `observability` прототипа этого не включает**:
проверять `channels`/`loggers`/`stats.log_snapshots` бессмысленно, они про логи и про
темп снапшота, а не про колонку `metric`. Воспроизводящей правки `system.yaml`, делающей
тест 4 зелёным, не существует — поэтому правка/возврат `apps/line_sim/system.yaml` не
делались (дерево не трогал).

## 3. Критерий 5 — плоскость ошибок работает; неверен путь в тесте

Прогон B (порт 5021 занят родителем → `SimRobotHostPlugin._probe_port_free` падает →
`report_error`). Листинг `MULTIPROCESS_LOG_DIR`:

```
ProcessManager/{messages.log 7787, performance.log 6509, system.log 0}
robot/{messages.log 4765, performance.log 4480, system.log 124}
launcher/{critical.log 0, errors.log 0, messages.log 989, performance.log 0, system.log 0, warnings.log 0}
critical.log 0   errors.log 536   warnings.log 0        <-- КОРЕНЬ каталога
observability.db 155648
```

`errors.log` (корень, 536 Б):

```
#13 2026-09-20 19:56:57,774 [ERROR] robot: sim_robot_host.start: [Errno 48] Address already in use
Traceback (most recent call last):
  File ".../Plugins/sim/robot_host/plugin.py", line 128, in _start_server
  ...
OSError: [Errno 48] Address already in use
```

`introspect.observability` того же прогона: `counters.error.channel_written_records = 1`,
`channel_written_by_channel = {errors_file: 1}`, `history.rows.error = 1`.

**Плоскость ошибок исправна.** Путь — по контракту, а не по дефекту:
* `error_module/configs/error_manager_config.py:44` — `error_file_path` по умолчанию
  `"logs/errors.log"`, без сегмента процесса;
* `process_module/configs/managers_config.py:198-199` —
  `error_file_path=os.path.join(log_dir_s, "errors.log")`, тот же `log_dir_s`, что у логгера;
* `multiprocess_framework/docs/observability/ACCEPTANCE_CHECKLIST.md:61` — дословно:
  «плоскость ошибок — **`<log_dir>/errors.log`, `warnings.log`, `critical.log` — в корне,
  ОБЩИЕ для всех процессов**; не per-process… Лаунчер держит свой набор в `launcher/`»;
* `docs/claude/OPEN_QUESTIONS.md:850` — тот же факт как открытый вопрос (семь
  `RotatingFileHandler` на один путь).

Тестер сам назвал это допущением: `docs/reviews/2026-09-20_task-1.1-tester.md:79,94` —
«`<log_dir>/<process>/errors.log` — **по аналогии** со структурой логов». Это тот самый
«wrong model теста», который правило проекта велит разрешать в пользу кода и записывать.

**Предупреждения `idle_sinks` — НЕ дефект.** `channel_routing_module/tests/test_idle_sinks.py:173`
пинит ровно это: `assert manager.idle_sinks(), "до первой ошибки приёмники ошибок молчат"`.
Разработчик прочитал их как доказательство сломанной маршрутизации — эта половина его
отчёта неверна. В прогоне B, где ошибка была, `warnings_file`/`critical_file` остались
idle, а `errors_file` из списка ушёл.

Вторая ветка ИЛИ в тесте (`anomalies` с «modbus») мертва по другой причине: аномалию
`health_errors` строит `backend_ctl/overview.py:_health_signals` из ветки
`processes.<p>.health` state-дерева, а её публикует heartbeat через `StateProxy`, которого
у `GenericProcess` нет (см. §4, вторая половина Q2). В прогоне B `anomalies` =
`[{"kind": "telemetry_readmodel_empty", …}]`.

## 4. Критерий 3 — корень и зелёное воспроизведение

Цепочка (якоря):
1. `backend_ctl/overview.py:150-155` — `topology = drv._state_topology()`; пусто → `processes: {}`
   + аномалия `empty_topology`.
2. `backend_ctl/driver.py:2393` — `send_command("ProcessManager", "state.get_subtree", …)`.
3. `app_module/orchestrator.py:_setup_state_store` (хвост файла):
   `initial_state = self.get_config("initial_state") or {}` … `if not initial_state and not
   throttle_rules: return` — `StateStoreManager` не создаётся, `register_commands` не
   зовётся, хендлера `state.get_subtree` нет (отсюда стек warning'ов в stderr).
4. `app_module/builder.py:283-289` — на generic-дороге `initial_state = {}`, если
   `AppSpec.state_bootstrap is None`. У `apps/line_sim` хука нет.

**Воспроизведено зелёным (прогон B).** Хук отдаёт ТОЛЬКО топологию из blueprint —
подмножество `multiprocess_prototype/backend/state/bootstrap.py:203-215` без прикладных
веток (`system`/`wires`/`services`/`displays`/`recipes`/`plugins`):

```python
def topo_bootstrap(blueprint):
    procs = {}
    for p in (blueprint.get("processes") or []):
        n = p.get("process_name") or ""
        if not n: continue
        procs[n] = {"config": {"plugins": list(p.get("plugins") or []),
                               "chain_targets": list(p.get("chain_targets") or []),
                               "priority": p.get("priority") or "normal"},
                    "state": {"status": "stopped", "pid": None, "fps": None, "error": None}}
    return {"processes": procs}

spec = AppSpec(manifest_path=ROOT/"apps/line_sim/app.yaml", state_bootstrap=topo_bootstrap)
```

`drv.system_overview()` →

```
processes = {"ProcessManager": {"ok": true, "status": "running", "workers": {...}, ...},
             "robot":          {"ok": true, "status": "running",
                                "workers": {"data_receiver": "running", "pipeline_executor": "running",
                                            "message_processor": "running", "heartbeat_sender": "running"}, ...}}
anomalies = [{"kind": "telemetry_readmodel_empty", ...}]      # empty_topology ИСЧЕЗЛА
```

`_find_process_entry(overview, "robot")` находит запись, `_entry_is_running` видит
`status == "running"` → **критерий 3 зелёный без единой правки плагина и конфига.**

Две находки поверх:
* **`ProcessManager` появился в дереве, хотя посев его не содержал** — дети и PM
  самопубликуются, как только стор существует. Посев нужен не как содержимое, а как
  НЕПУСТОЙ dict: гейт в `_setup_state_store` — `if not initial_state`, и `{"processes": {}}`
  его уже проходит. Значит дефолтный хук может быть тонким.
* **`ctx.state_proxy` у `GenericProcess` по-прежнему нет** (слот объявлен —
  `process_module/core/process_module.py:109,133,720-736`, но generic-процесс его не
  заводит; прототипный делает это в `GenericProcessApp._init_custom_managers`). Следствие —
  ветка `processes.<p>.health` не публикуется, `health_errors` не появляется. Это отдельный
  carve-out, в плане он уже назван Task 2.0; критерию 3 он НЕ нужен.

## 5. ESCALATION -> cto (развилка критерия 4)

```
ESCALATION -> cto
Question: критерий 4 требует `history_query(metric="sim_robot.writes") >= 1 строка`.
  Какой из трёх вариантов принимаем?
  (а) правка ТЕСТА: спрашивать `history_query(kind="stats")` + имя метрики в
      `extra.metrics[].name` (дёшево, честно, пинит существующий контракт);
  (б) правка ПЛАГИНА: добавить `ctx.publish_metric("writes", total)` — уровень порта
      наблюдений. Строка с `metric` появится, но идентичность будет
      `sim_robot_host.writes` (writer = plugin_name), а литерал теста `sim_robot.writes`;
      значит правка теста всё равно нужна, плюс нужен живой такт гейта наблюдений;
  (в) правка ФРЕЙМВОРКА: подцепить store-tap к `ObservationManager` в
      `process_module/core/process_module.py:602-612` (`wire_observability_store`
      принимает сегодня только error+logger). Тогда КАЖДЫЙ `record_metric` станет
      строкой стора — замерено 201 число за ~6 с на ПРОСТАИВАЮЩЕМ robot; это отмена
      агрегации как политики, не локальная правка.
Tried: прогон A (sqlite group-by: metric IS NULL во всех 68 строках), чтение
  observability_store.py:783-787, record_display.py:213-218, number_record.py:82-120;
  сверка с живым стендом прототипа — probe_observability_consumer_acceptance.py:669-674
  («на inspection_full записей с metric нет вовсе»).
Blocked on: решение «менять тест / менять плагин / менять политику агрегации» —
  оно переживает Task 1.1 и задаёт контракт наблюдаемости второму приложению.
Files: apps/line_sim/tests/test_f1_task11_acceptance.py, Plugins/sim/robot_host/plugin.py,
  multiprocess_framework/modules/process_module/core/process_module.py
```

Мой совет (не решение): **(а)**, и записать в ADR, что «число с именем» у плагина —
это `publish_metric`/уровень, а `record_metric` — слагаемое агрегата без идентичности.
Вариант (в) ломает свойство, которое фреймворк защищает сознательно.

## 6. Спека Task 1.0 для teamlead (executor-brief)

```
TASK: 1.0 — дефолтный StateBootstrap в app_module: generic-приложение поднимает
  state-плоскость и отвечает на state.get_subtree без единого хука
  PLAN: plans/line-sim/phase-1-vertical-slice.md (§Task 1.1, §Разведка)
ROLE: teamlead
CHAIN: investigator (docs/reviews/2026-09-20_line-sim-generic-app-observability-investigation.md)
  -> you -> tester (RED до тебя, по критериям приёмки ниже) -> reviewer

DESIGN (решено lead'ом — ты это набираешь, а не выводишь):
  Завести во фреймворке дефолтный build-time хук `default_state_bootstrap(blueprint) -> dict`
  рядом с `default_blueprint_loader` (`multiprocess_framework/modules/app_module/builder.py:93-115`)
  и применять его в `SystemBuilder._build_generic` там, где сейчас стоит
  `initial_state: dict[str, Any] = {}` (builder.py:283-289): `spec.state_bootstrap or
  default_state_bootstrap`. Хук строит ТОЛЬКО топологию — `{"processes": {<process_name>:
  {"config": {"plugins": [...], "chain_targets": [...], "priority": "normal"},
  "state": {"status": "stopped", "pid": None, "fps": None, "error": None}}}}` — подмножество
  `multiprocess_prototype/backend/state/bootstrap.py:203-215` БЕЗ прикладных веток
  (`system`/`wires`/`services`/`displays`/`recipes`/`plugins`): они читают `SystemConfig`
  и реестры прототипа, которых у generic-приложения нет. Результат пиклится через spawn,
  поэтому только plain dict/list/str/None (`_pickle_sanity` это уже проверит).
  НЕ менять: `_setup_state_store` (`app_module/orchestrator.py`) — его гейт
  `if not initial_state and not throttle_rules` остаётся как есть, непустой посев его
  проходит; `assemble_proc_dicts`; раскладку слоёв наблюдаемости; прототипную
  factory-дорогу (`spec.launcher_factory` — ветка `build()` до `_build_generic`).
  Явный `AppSpec.state_bootstrap` по-прежнему выигрывает у дефолта.
  ADR — в `multiprocess_framework/modules/app_module/DECISIONS.md` (почему топология,
  а не пустой dict, и почему прикладные ветки не переезжают).

FILES (полный список — больше ничего; нужен другой файл -> стоп и вопрос lead'у):
  1. multiprocess_framework/modules/app_module/builder.py — `default_state_bootstrap`
     + применение в `_build_generic` (строки 283-289)
  2. multiprocess_framework/modules/app_module/__init__.py — экспорт символа
  3. multiprocess_framework/modules/app_module/README.md — абзац про дефолтный хук
  4. multiprocess_framework/modules/app_module/DECISIONS.md — ADR
  5. multiprocess_framework/modules/app_module/tests/test_contract.py — контракт-тест хука
  6. multiprocess_prototype/backend/state/bootstrap.py — ТОЛЬКО комментарий-алиас
     «топологическая половина живёт в app_module.default_state_bootstrap»; код не трогать

REDS (предсказанные красные, <= 10):
  - multiprocess_framework/modules/app_module/tests/test_contract.py::test_default_state_bootstrap_builds_topology
  - multiprocess_framework/modules/app_module/tests/test_contract.py::test_generic_build_seeds_initial_state
  - examples/minimal_app/tests/test_ci_smoke.py::test_system_overview_lists_processes   (новый)
  - apps/line_sim/tests/test_f1_task11_acceptance.py::test_backend_ctl_sees_robot_and_status

ACCEPTANCE (числа, которые lead проверит прогоном — измеримы тестером вслепую):
  1. `examples/minimal_app`: `drv.system_overview()["processes"]` содержит имя процесса из
     `pipeline.yaml` со `status == "running"`; в `anomalies` НЕТ `kind == "empty_topology"`.
     Сегодня — `processes == {}` + `empty_topology`.
  2. `apps/line_sim`: `pytest apps/line_sim/tests/test_f1_task11_acceptance.py -q` →
     `test_backend_ctl_sees_robot_and_status` зелёный БЕЗ правок `Plugins/sim/*` и
     `apps/line_sim/*`. Сегодня — падает на `processes == {}`.
  3. `drv.send_command("ProcessManager", "state.get_subtree", {"path": "processes"})` →
     `success: true`; в stderr прогона НЕТ строки `No handler for key 'state.get_subtree'`.
     Сегодня — ~20 таких строк за 10 с.
  4. Явный `AppSpec(state_bootstrap=my_hook)` по-прежнему выигрывает: посев в
     `orchestrator_config["initial_state"]` равен результату `my_hook`, не дефолта.
  5. Прототип не задет: `python scripts/run_framework_tests.py` не ниже baseline;
     `sentrux check .` — `✓ All rules pass` (CLI, не MCP).
  6. Ни один файл вне FILES не изменён (`git show --stat`).

FIRST EDIT: в первых 5 вызовах инструментов. DESIGN не выводить заново; файлы вне FILES
  не открывать. Перед первой правкой под `multiprocess_framework/` — ОДНО сообщение наверх
  (<= 300 токенов): DESIGN (3 строки) / FILES / starting edits.

TESTS: `PYTHONPATH=$PWD .venv/bin/python -m pytest
  multiprocess_framework/modules/app_module/tests/test_contract.py
  examples/minimal_app/tests/test_ci_smoke.py
  apps/line_sim/tests/test_f1_task11_acceptance.py::test_backend_ctl_sees_robot_and_status
  -q --tb=short`

TEST RULES: foreground, `timeout: 300000`, никогда полную сьюту (её гонит lead на точке
  слияния). Дерево `.claude/worktrees/line-sim`, venv общий, `PYTHONPATH=$PWD`,
  `uv sync` НЕ запускать. Порт 5021 свободен; 8765 не трогать. qex не использовать —
  индекс от 13 сентября (7 дней), числа считать грепом.

BUDGET: «Context checkpoint» — решение, не стоп: закоммитить работающее; остаток меньше
  ~30 вызовов → доделать без handoff; иначе — `docs/handoffs/2026-09-20_task-1.0-teamlead.md`.

REPORT (финальное сообщение, <= 25 строк): ПЕРВАЯ СТРОКА
  `STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`; каждое число приёмки — из
  команды, которая его дала; файлы; «что интерпретировал, а не исполнил»; «что оставил
  открытым / ненадёжно» (непустой). Полный отчёт —
  `docs/reviews/2026-09-20_task-1.0-teamlead.md`, путь назвать.

OUT OF SCOPE: `ctx.state_proxy` для `GenericProcess` и ветка `processes.<p>.health`
  (это Task 2.0 плана); критерий 4 (`history_query(metric=)`) — ждёт решения cto, §5;
  критерий 5 (путь `errors.log`) — правка ТЕСТА в Task 1.1, не фреймворка; кадры (Task 1.2).
TRAPS: (1) `MULTIPROCESS_LOG_DIR` ставить ДО сборки launcher'а. (2) Хук исполняется в
  РОДИТЕЛЕ, результат едет через spawn — только pickle-safe примитивы. (3) Гейт
  `_setup_state_store` смотрит на ИСТИННОСТЬ dict'а: `{}` не проходит, `{"processes": {}}`
  проходит — решить осознанно, что отдавать при blueprint без процессов, и пришпилить тестом.
HANDOFF IN: none
COMMIT: Conventional Commits + `Why:`/`Layer: framework`/`Refs: plans/line-sim/phase-1-vertical-slice.md`.
```

## 7. Что из этого — конфиг сима (Task 1.1), а что — фреймворк (Task 1.0)

| Правка | Куда |
|---|---|
| дефолтный `StateBootstrap` в `app_module` | **Task 1.0**, фреймворк |
| `apps/line_sim/system.yaml` | **не трогать**: ни один ключ прототипа не чинит критерии 4/5; нынешние 7 листьев доехали — `provenance` показывает `layer: app` и адрес файла для `errors.*`, `stats.*`, `history.*` |
| путь `errors.log` в приёмочном тесте (`<log_dir>/errors.log`) | **Task 1.1**, тест |
| критерий 4 — форма запроса истории и/или дорога метрики в плагине | **решение cto**, §5 |
| `ctx.state_proxy` у `GenericProcess`, ветка `health` | Task 2.0 (как и планировалось) |

## 8. Что оставил открытым / ненадёжно в своей работе

* **`канал 'messages_file' не резолвится` у `robot` и `ProcessManager`** (счёт 1 за прогон,
  оба прогона) — при этом `robot/messages.log` непустой (4765 Б) и
  `channel_written_by_channel.messages_file = 31`. Похоже на гонку старта: один-два первых
  записи уходят до резолва канала. **Не расследовал**, в корень критериев 3/4/5 не входит.
* **Общий `<log_dir>/errors.log` на все процессы** — по контракту, но это семь
  `RotatingFileHandler` на один путь; ротация из разных процессов не проверялась
  (уже записано в `docs/claude/OPEN_QUESTIONS.md:850`). Я это не проверял тоже.
* **Прототип на критериях 4/5 прогоном не проверял.** Вывод про прототип построен на
  чтении кода (общий `process_module`) и на ЗАПИСАННОМ замере чужого прогона
  (`probe_observability_consumer_acceptance.py` R12) — это цитата, а не мой стенд.
* **Критерий 4 зелёным не воспроизводил ни одним вариантом.** Я показал, почему он красный,
  и назвал три дороги; какая из них даст зелёный — не измерено. Вариант (б) вдобавок зависит
  от такта гейта наблюдений (`evaluated_ticks = 0` у robot), а я не проверял, оживает ли
  гейт от первого `publish_metric`.
* **Критерий 3 воспроизведён зелёным на ОДНОМ прогоне** (`system_overview`), не полным
  телом теста `test_backend_ctl_sees_robot_and_status` — вторая половина теста
  (`sim_robot.status` с host/port/unit_id) в прогоне B была зелёной отдельным вызовом,
  но тест целиком я не гонял с хуком.
* **`stats: 0` в прогоне B** против `stats: 2` в прогоне A — прогон B короче. Числом темпа
  снапшота я не занимался.
* qex не использовал (индекс от 13 сентября — семь дней); все якоря `файл:строка` получены
  `grep`/чтением файла.
