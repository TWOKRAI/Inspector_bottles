# C-82 — выжимка для слепого тестера

> Единственный вход тестера. Этот файл — копия раздела из [`C-82.md`](C-82.md); тестеру передаётся только он.

## Для слепого тестера (выжимка — единственный вход тестера)

Пиши приёмку только по этим критериям. **Запрещено читать:** `plans/**` (кроме этого файла), `docs/reports/**`,
`docs/reviews/**`, `multiprocess_framework/modules/app_module/orchestrator.py`, `multiprocess_prototype/backend/orchestrator_hooks.py`,
`multiprocess_framework/modules/process_manager_module/runner/process_runner.py` дальше сигнатур. Разрешено: публичные
сигнатуры, README модулей, существующие тесты как образцы обвязки.

1. У `GenericProcessManagerApp` есть `boot_stop_requested() -> bool`: `True`, если взведён `stop_event` процесса или
   системный стоп.
2. Если стоп взведён до или во время `initialize()` оркестратора, runtime-seam `_configure_runtime()` и
   observability-watcher не запускаются, а `initialize()` возвращает `True` (это не провал подъёма: нет состояния
   `error`, нет строки `Process initialization failed`).
3. Раннер процесса (`run_process_function`): если к концу `initialize()` взведён `stop_event` или `system_stop_event`,
   `run()` не вызывается, `stop()` вызывается ровно один раз, корень закрывается; без стопа — `run()` вызывается как
   раньше.
4. PM с `_configure_runtime`, который спит 6,0 с, и стопом, взведённым до входа в seam, выходит за < 3,0 с от стопа.
5. Хук прототипа `configure_topology_engine(orchestrator)`: если `orchestrator.boot_stop_requested()` — `True` до
   вызова, `discover` плагинов не вызывается и движок топологии не конфигурируется; без стопа — оба вызываются.

Ожидаемые значения — литералы. Тест, который может зависнуть, — daemon-поток с `join(deadline)`. Разрешённые файлы —
два из FILES «Тестер».
