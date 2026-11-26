# Task W1-c: имя процесса в строках плагинов с первой строки configure

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** impl-only (`process_module/core/process_module.py`, порядок шагов `initialize`)
- **Dependencies:** нет
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; база красных `process_module/tests` и `logger_module/tests` — снимок лида на `85a7906d1`
- **Files:** `multiprocess_framework/modules/process_module/core/process_module.py`, `multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py`
- **Acceptance:** блок ACCEPTANCE; файл tester-а зелёный
- **Handoff:** reviewer (стадия 0) -> tester (слепой, RED, процесс spawn) -> developer -> лид (инъекции) -> reviewer (стадия 5, opus)
- **ФАЙЛ TESTER-А (developer не правит):** `multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py`

Диагноз (код; подтверждён живым логом ревьюера: строки фазы старта камеры #14-#28 — `[-]`). `proc_name` в строку файла кладёт `FileChannel.write` (`logger_module/channels/log_channel.py`, `_emit` с `:1044`, `:1057`) из `record["extra"]`; `extra` собирает `LoggerCore` из базы процесса (`logger_core.py:1923-1928`). Базу ставит шаг 9 `ProcessModule.initialize` (`process_module.py:322-330`). Плагины конфигурируются и стартуют раньше, на шаге 6: `_init_custom_managers()` (`:291`) создаёт оркестратор, `_init_application_threads()` (`:292`) зовёт `self._orchestrator.boot()` (`:1060-1061`), в `boot()` синхронно `plugin._do_configure(ctx)` (`plugin_orchestrator.py:237`) и `plugin._do_start(ctx)` (`:262`). Решение: база — сразу после появления логгера (шаг 3a). Отвергнуто: префиксы в `ctx.log_*` (второй механизм имени); правка `log_channel.py` (горячий путь записи; цель — данные); база внутри `ProcessManagers._create_logger_manager` сразу после `logger.initialize` (`process_managers.py:301`) — покрыла бы и строки шага 3, но это второй файл и тесты с фейковым `process` (`**Mock` -> `TypeError`); пока 3a.

TASK: W1-c — база контекста логгера ставится до загрузки плагинов   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: reviewer (стадия 0) -> tester (слепой RED) -> you -> лид (инъекции) -> reviewer (стадия 5, opus)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. В `ProcessModule.initialize` перенести блок шага 9 (`logger = self.get_manager("logger")`; `if logger and hasattr(logger, "set_base_context"): logger.set_base_context(**self._build_resource())`) СРАЗУ после `self._init_managers()` (шаг 3), до `self._init_communication()`. Комментарий — вместе с блоком, номер `3a`, плюс фраза: «до шага 6: плагины пишут в `configure`/`start` внутри `boot()`, их строки должны нести имя процесса (W1-c)». На месте шага 9 ничего не оставлять: вызов один.
  2. Безопасность переноса проверена ревьюером: `_build_resource()` (`process_module.py:887-974`) читает `self.name`, `os.getpid()`, версию кода, `incarnation` из PSR (`routing_incarnation` засевается до создания `ProcessModule`, `bundle_builder.py:70-73`), `recipe` из конфигурации; все виды процессов идут через `ProcessModule.initialize`. Метод глушит любое исключение (`:944,953,971`) — поэтому тест п.4 проверяет, что `incarnation` и `recipe` доехали.
  3. Не менять: `log_channel.py` (`or "-"` на `:1057` и `:1129`), `logger_core.py`, `set_base_context`, порядок прочих шагов, `clear_base_context` в `process_lifecycle`.
  4. Тесты developer-а (`test_log_base_context_order.py`), образец — `test_process_resource.py:313` (настоящий `ProcessModule("name").initialize()` на пустой конфигурации) и `add_tap` (`:370`). Подкласс `ProcessModule` переопределяет `_init_custom_managers`: `super()._init_custom_managers()`, затем `self.get_manager("logger").add_tap(sink, min_level="DEBUG", name="w1c")` (tap ставится только после появления логгера, то есть здесь), `self.log_info("w1c-step6")`; второй тест — то же из потока, созданного в хуке и присоединённого в нём же с дедлайном (`join(2.0)`); `shutdown` в `finally`. Запись ищется в `sink` по тексту `w1c-step6` (не `sink.records[0]`: до хука в tap идут и другие строки). Ожидание: `extra["proc_name"] == "w1c_proc"`. Третий тест — настоящий `initialize()` с настоящим PSR (помощник `_process(metadata=...)` из `test_process_resource.py:78-93` строит процесс через `__new__` с фейковым PSR и не годится; у `ProcessModule("w1c_proc")` `shared_resources=None`, `process_module.py:131`, и `incarnation` не появится): `srm = SharedResourcesManager()`; до `initialize()` — `srm.process_state_registry.register_process("w1c_proc", initial_state={"metadata": {"routing_incarnation": 5}})` (`process_state_registry.py:75`, ветка `metadata`); `ProcessModule("w1c_proc", shared_resources=srm, config={...})`, где `observability_recipe_path` указывает на существующий временный YAML (шаг 3 его читает, `process_module.py:716-727`); в записи `w1c-step6`: `extra["incarnation"] == 5`, `extra["recipe"]` = имя файла рецепта. Все три красные до правки по одной причине — на шаге 6 базы нет совсем; ценность третьего — после правки: он сторожит молчаливое проглатывание исключений в `_build_resource` (`:944,953,971`).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/process_module/core/process_module.py — блок базы контекста на шаг 3a
  2. multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py — новый, три теста п.4

REDS (predicted red tests):
  - multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py::test_configure_line_of_plugin_carries_process_name
  - multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py::test_start_line_of_plugin_carries_process_name
  - multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py::test_step6_record_has_proc_name
  - multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py::test_step6_thread_record_has_proc_name
  - multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py::test_step6_record_has_incarnation_and_recipe

ACCEPTANCE (every number with its command):
  - оба файла зелёные — `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py` -> exit 0
  - охранный `test_shutdown_line_of_plugin_carries_process_name` tester-а зелёный и до правки, и после
  - радиус `multiprocess_framework/modules/process_module/tests` и `multiprocess_framework/modules/logger_module/tests` (medium, по одному) — красные не шире снимка лида
  - `ruff check -q multiprocess_framework/modules/process_module/core/process_module.py multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py` -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_log_base_context_order.py multiprocess_framework/modules/process_module/tests/test_plugin_log_proc_name_mp.py   (`<py>` — python основного `.venv`, `PYTHONPATH=<корень worktree>`)

OUT OF SCOPE: строки #1-#7 каждого процесса остаются `[-]` (инициализация логгера, router/stats/observation внутри `create_all` шага 3, повторный `StatsAdapter`, `Process starting...` из `process_runner.py:372`) — около 7 из 36 строк окна старта; фильтр «Источник» панели «Логи» (T10); `observability.db`; тест пропускной способности (горячий путь не меняется).
TRAPS: если RED tester-а `test_configure_line_...` ЗЕЛЁНЫЙ до правки — посылка ложна, СТОП и отчёт; tap до шага 3 поставить нельзя — только в хуке шага 6; если настоящий `initialize()` с настоящим `SharedResourcesManager` не поднимается (или `register_process` не кладёт `metadata`) — СТОП и отчёт, обходной стенд не строить.
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
