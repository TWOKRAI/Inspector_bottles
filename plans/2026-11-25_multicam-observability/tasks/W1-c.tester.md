# W1-c — бриф tester

Спавн: `python scripts/plans_ledger.py brief W1-c.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W1-c — слепой тест имени процесса в строках плагина из процесса, запущенного через spawn (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> developer (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ: каждая строка, которую плагин пишет через `ctx.log_info`, в `messages.log` процесса (формат `%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s`, `logger_module/configs/logger_manager_config.py:21`; `%(name)s` — имя плагина из `plugin_name`) несёт `[<имя процесса>]`, в том числе строки из `configure` и `start` плагина, а не `[-]`.
  2. Запуск — настоящий дочерний процесс: `ctx = multiprocessing.get_context("spawn")`; `stop = ctx.Event()`; `ctx.Process(target=run_process_function, args=("multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess", "w1c_child", stop, bundle, None), daemon=True)`; `run_process_function` — `multiprocess_framework/modules/process_manager_module/runner/process_runner.py:296`. `bundle` — по образцу `_Stand` в `multiprocess_framework/modules/process_module/tests/test_heartbeat_paused_push.py:160-180` (ключи `queues`, `config`, `custom.process_config`, `custom.ready_event`), но все очереди и события — из `ctx`; плагины — `{"plugins": [{"plugin_class": "<модуль теста>.W1cProbe", "plugin_name": "w1c_probe"}], "chain_targets": []}`. Каталог лога — временный каталог теста через `config.managers.logger.log_directory` (`logger_manager_config.py:298`; канал `messages_file`, `file_path="messages.log"`, `:447-450`). Образец сам запускает процесс в потоке (`:183-189`) — здесь НЕ так: нужен отдельный процесс.
  3. Плагин-зонд `W1cProbe` — на уровне модуля нового файла (spawn импортирует его по имени), `@register_plugin("w1c_probe", category="processing")` из `multiprocess_framework.modules.process_module.plugins`: `configure` пишет `ctx.log_info("w1c-configure-line")`, `start` — `ctx.log_info("w1c-start-line")`, `shutdown` — `ctx.log_info("w1c-shutdown-line")`. Тест ждёт строку `w1c-start-line` в `<log_dir>/w1c_child/messages.log` с дедлайном 30 с, затем `stop.set()`, `join(15)`, при живом процессе — `terminate()`; всё в `finally`.
  4. Сценарии и литералы:
     - `test_configure_line_of_plugin_carries_process_name`: ровно одна строка с `w1c-configure-line`, в ней подстрока `[w1c_child] w1c_probe: w1c-configure-line`; подстроки `[-] w1c_probe` нет ни в одной строке файла.
     - `test_start_line_of_plugin_carries_process_name`: строка с `w1c-start-line` содержит `[w1c_child] w1c_probe: w1c-start-line` (старт плагина идёт в `boot()` шага 6 — до кода красный).
     - `test_shutdown_line_of_plugin_carries_process_name` (охранный, зелёный и до кода): строка `w1c-shutdown-line` содержит `[w1c_child] w1c_probe: w1c-shutdown-line`.
  5. Если файл `messages.log` не появился в каталоге теста за 30 с или ключ `log_directory` лежит по другому пути — СТОП и отчёт с найденным путём, свой запуск процесса не придумывать. Один процесс на тест-модуль допустим (фикстура `scope="module"`), три теста читают один файл.
  6. Новый `.py`: `__all__ = []`, строка `Purpose:`.

FORBIDDEN PATHS (no edits, no reads of implementation): multiprocess_framework/modules/process_module/core/process_module.py, multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py, plans/2026-11-25_multicam-observability/tasks/W1-c.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py — new

REDS (expected RED before code):
  - multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py::test_configure_line_of_plugin_carries_process_name
  - multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py::test_start_line_of_plugin_carries_process_name

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py

OUT OF SCOPE: реализация, юнит-тесты порядка шагов (у developer-а), `observability.db`, панель «Логи».
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных: два RED падают по утверждению о `[-]`, не по запуску процесса; охранный тест зелёный.
