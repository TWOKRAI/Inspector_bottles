# C-60 — выжимка для слепого тестера

> Единственный вход тестера. Тестер работает в worktree от main `da3febe8e`, где брифа нет; лид передаёт этот текст
> в промпте. Внутреннее устройство остановки процесса тестеру не известно и не проверяется.

## Что должно стать правдой

Плагин процесса получает весть «стоп процесса начат» раньше, чем остановка процесса ждёт долгие операции его
воркеров и именованных исполнителей. `shutdown` плагина по-прежнему идёт после остановки воркеров процесса.

## Публичный контракт (новый необязательный хук плагина)

`ProcessModulePlugin.request_stop(self, ctx: PluginContext) -> None`, умолчание — ничего не делает.
- Зовётся на закрытии процесса (`proc.shutdown()`), раньше ожидания воркеров и исполнителей процесса и раньше
  `shutdown` плагина; плагины — в порядке, обратном загрузке (как `shutdown`).
- Не зовётся одним `proc.stop()` без закрытия; не зовётся плагину, чей `configure` бросил.
- Хук запускает остановку и возвращается, не ждёт.
- Один вызов хука на закрытие процесса: повторный `proc.shutdown()` хук не повторяет. Прямой повторный вызов
  кода, который зовёт хуки (вне обычного закрытия), может вызвать хук ещё раз — поэтому хук должен быть идемпотентным;
  в приёмке это не проверяется.
- Исключение хука одного плагина не мешает хуку соседа, остановке воркеров и `shutdown` плагинов; `proc.shutdown()`
  при этом возвращает `True`.

## Обвязка (публичное API)

- Процесс: `ProcessModule(name, config={"config": {"executors": {"io": {"serial": True}}, "plugins": [{"plugin_name":
  "probe", "plugin_class": "<модуль теста>.ProbePlugin"}]}})`; `proc.attach_stop_budget({"work_s": W, "infra_s": 0.25})`
  до `proc.initialize()` (без вызова — умолчание процесса, `W` = 3,0 с). **Каждому процессу — уникальное имя**
  (в т.ч. в повторах внутри теста): процессы одного интерпретатора делят слоты процессных хуков по имени.
- Долгая операция: `proc.executor_manager.get("io").submit(action, frozenset({"k"}), reply)` (протокол
  `OrderedExecutor`, `worker_module/interfaces.py`); `action` ставит событие «начало», ждёт `threading.Event` до `L`
  секунд, пишет момент конца.
- Плагин-зонд пишет в **общий журнал событий** (список в порядке вызова, под замком) строки
  `"<имя>.request_stop"`, `"<имя>.shutdown"`, `"<имя>.worker_exit"`; для задержек — ещё `time.monotonic()`.
  Свой воркер (`ctx.worker_manager.create_worker(...)` в `start`, цикл до `stop_event`) — только у зонда R1, R1b, R2,
  R5. В R3/R4 плагины **без воркера**, `worker_exit` в их журнал не попадает.
- `t0 = time.monotonic()` прямо перед `proc.shutdown()`; вызов — в daemon-потоке с `join(30)`. В `finally` —
  взвести событие операции и вызвать `proc.shutdown()` ещё раз.
- «Первая весть» = минимум моментов `request_stop` и `shutdown` плагина.
- **Порядок проверять только по журналу событий.** Моменты `monotonic` — только для задержек ≥ 0,1 с: шаг часов
  на Windows 15,625 мс, разности меньше ~0,1 с недостоверны.

## Тесты (`multiprocess_framework/modules/process_module/tests/test_plugin_stop_request_acceptance.py`)

- **R1 `test_plugin_hears_stop_before_long_executor_op_ends`** — `W` = 1,0, `L` = 2,5, операция начата до `t0`.
  Ждём: первая весть − `t0` ≤ 0,25 с; конец операции − первая весть ≥ 1,0 с. n = 5 процессов (`c60r1_0`…`c60r1_4`),
  порог на каждый. На main ожидается красный: первая весть ≈ 1,0 с (воспроизведено: 1,016 с).
- **R1b `test_plugin_hears_stop_before_long_op_default_budget`** — без `attach_stop_budget`, `L` = 4,0. Ждём: первая
  весть − `t0` ≤ 0,25 с. На main красный, ≈ 3,0 с. n = 1.
- **R2 `test_plugin_shutdown_still_after_own_workers_stop`** (страж, зелёный до и после) — как R1: `shutdown` − `t0` ∈
  [0,95; 1,40] с; в журнале `probe.worker_exit` раньше `probe.shutdown`.
- **R3 `test_stop_request_reaches_running_plugins_once_in_reverse_order`** — плагины A (загружен первым) и B, оба
  без воркера, без долгой операции; `proc.shutdown()` дважды. Журнал ровно `["B.request_stop", "A.request_stop", "B.shutdown",
  "A.shutdown"]`. На main красный: `["B.shutdown", "A.shutdown"]`.
- **R4 `test_stop_request_failure_does_not_block_neighbours`** — A (первым) обычный, у B (вторым) `request_stop`
  пишет в журнал и бросает `RuntimeError`; оба без воркера, без долгой операции. Журнал ровно `["B.request_stop", "A.request_stop",
  "B.shutdown", "A.shutdown"]`; `proc.shutdown()` вернул `True` за ≤ 2,0 с. На main красный.
- **R5 `test_plugin_without_hook_unchanged`** (страж) — плагин без `request_stop`, как R1: `shutdown` − `t0` ∈
  [0,95; 1,40] с, исключений нет.

Команда (cwd и `PYTHONPATH` — корень worktree, основной `.venv`, без `uv sync`):
`bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-aa
<.venv python> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_plugin_stop_request_acceptance.py`

## Запрещено читать

`plans/lifecycle-stop-ownership/tasks/C-60*.md` (кроме этой выжимки), `plans/lifecycle-stop-ownership/reports/C-60*`,
строку C-60 в `plans/queue/defects.md`; реализацию: `multiprocess_framework/modules/process_module/core/**`,
`process_module/lifecycle/**`, `process_module/generic/**`, тело `process_module/plugins/base.py`, любую реализацию жизненного цикла процесса,
областей владения и исполнителей/воркеров (`base_manager/core/**`, `worker_module/**`, кроме `worker_module/interfaces.py`). Можно: `worker_module/interfaces.py`, README модулей, существующие тесты
`process_module/tests/test_process_root_acceptance.py` и `test_process_executors_acceptance.py` как образец обвязки.
Не коммитить, не пушить.
