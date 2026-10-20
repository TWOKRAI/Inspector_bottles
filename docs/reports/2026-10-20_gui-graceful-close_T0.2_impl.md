# Task 0.2 (gui-graceful-close) — стадия 2 GREEN, отчёт teamlead

Ветка `feat/gui-close-force-stop`, worktree `.claude/worktrees/gui-close-0.2`, поверх RED `9ea23994b`. Коммита нет.

## Diff stat

```
backend_ctl/AGENTS.md                                   |  1 +
backend_ctl/README.md                                   |  1 +
backend_ctl/driver.py                                   | 47 +++
backend_ctl/mcp_tools.py                                | 34 +++
multiprocess_framework/DECISIONS.md                     |  2 +-   (переписал scripts.sync)
process_manager_module/DECISIONS.md                     | 51 +++
process_manager_module/README.md                        |  2 +-
process_manager_module/process/process_manager_process.py | 63 ++++-
8 files changed, 196 insertions(+), 5 deletions(-)
```

## Шаги DESIGN → код

1. Валидация: `process_manager_process.py:685-698` (`_merge_cmd_args`, литералы ошибок, `bool`/не число/NaN/inf/вне 0.1..5.0; при ошибке возврат до событий). Добавлен `import math` (:12).
2. `force`: `:699-709` — `set_force_deadline` раньше событий, INFO `force: срок стопа детей <d> с`, ответ с `mode`/`deadline_s`; без `_children_stop` — WARNING + graceful, `"mode": "graceful"`. Graceful-путь (`:710-714`): та же строка лога, те же события, ответ `{"success": True, "message": "Shutdown initiated"}`.
3. `_ChildrenStop`: `_force_at`/`_killed` на уровне класса (`:4386-4388`), `set_force_deadline` под `_lock`, первый выигрывает (`:4425`), обрезка в `join_until` (`:4446-4447`), `kill()` ставит `_killed` до делегирования (`:4452`). Потока, таймера, нового `.kill()`/`.terminate()` нет.
4. `driver.py:679` `system_shutdown(...)`: `system_command(..., timeout=6.0)`; `deadline_s` уходит только при `force`; опрос `connection_lost` раз в 100 мс; `accepted=None` при `error == "timeout"`.
5. `mcp_tools.py:308` handler (зовёт `drv.system_shutdown(mode=, deadline_s=)` — без `timeout`, конфликта с D3 нет), spec `:852`, `TOOL_SAFETY["system_shutdown"] = SAFETY_ESCALATED` `:1572`. AGENTS.md — строка после `process_restart_verified`.
6. PM README (строка `system.shutdown`), backend_ctl README (строка `system_shutdown(...)`), ADR-PMM-038 `DECISIONS.md:1812` с пределами (а)–(д); `python -m scripts.sync` переписал только `multiprocess_framework/DECISIONS.md` (строка индекса PMM 001…038).

## Прогоны (через гейт, `PYTHONPATH=<worktree>`)

Путь импорта (cwd = worktree):
```
...\.claude\worktrees\gui-close-0.2\multiprocess_framework\__init__.py
...\.claude\worktrees\gui-close-0.2\backend_ctl\__init__.py
```
- U+D до: 18 failed, 2 passed (по брифу тестера). После: `20 passed, 1 warning in 3.36s` (повтор после документов: `20 passed, 1 warning in 2.35s`).
- Инъекции поломки (патч в процессе pytest): без флага `_killed` — `1 failed, 15 passed` (`test_join_after_kill_not_capped`: «после kill() срок 6899.1400 должен дойти до группы как есть, получено [6898.14]»); без «первый выигрывает» — `1 failed, 15 passed` («повторный force сдвинул срок»).
- Соседи (`test_stop_summary_live`, `test_system_shutdown_live`, `test_child_process_stop`, `test_process_manager_process`, `test_process_root_pm_hazards`, `test_self_reply_hazards`, `frontend/tests/test_gui_process`, 5 файлов MCP-реестра backend_ctl): `235 passed, 5 skipped, 1 warning in 21.06s`. Live-файлы без `--backend-live` — skipped.
- L: `--collect-only --backend-live` → `3 tests collected in 0.44s`. Не запускался (нужно окно стенда).
- `ruff check -q` → rc=0; `ruff format --check` → `3 files already formatted`.
- `validate.py` → rc=1, 3 FAIL: «память: ошибки тегов», «память: индекс BY-MODULE*.md устарел», «G6 R1 Services/code_reader/tools/thread_split_probe.py:210». Это те же 3, что в C-13 на main. Дельта: 0.

## Логи для L6

PM `_log_info`/`_log_warning` → `observable_mixin.py:169` (`_call_manager_result("logger", level, ...)`) → LoggerManager. Каталог: `harness.py:118-121` (`system.log_dir = log_dir`) → `multiprocess_prototype/backend/launch.py:662` (`resolve_log_dir_root`; env `MULTIPROCESS_LOG_DIR`/`INSPECTOR_LOG_DIR` сильнее, `launch.py:51-52`) → `logger_core.py:773-782` + `log_paths.py:32-50` → `<log_dir>/<имя процесса PM>/`. Файловый канал `system_file` → `system.log` (`logger_manager_config.py:441`), уровень по умолчанию INFO (`logger_manager_config.py:269`, `system.yaml:47 log_level: INFO`). Есть и канал console, `StreamHandler()` = stderr (`log_channel.py:1059`). Вывод: INFO `force: срок стопа детей 1.0 с` и WARNING `Process '<name>' did not stop in N.Ns, terminating...` (`child_process_stop.py:182` → `_emit` → `pm._log_warning`) должны попасть в `<log_dir>/<PM>/system.log`, а `_read_all_logs` (`rglob("*.log")`) их найдёт. Логирование не менялось.

## Что в DESIGN спорно (не менял)

- Шаг 4: при `accepted=False` (PM отверг аргументы, стоп не начат) драйвер всё равно ждёт `wait_timeout` (20 с) закрытия сокета, которое не наступит. Вход `system_shutdown(mode="force", deadline_s=9)` → ответ PM `{"error": ...}` → 20 с ожидания, `pm_gone=False`. Предлагаю не ждать при `accepted is False`; нужно решение лида.
- `mode` в возврате драйвера я беру из ответа PM (`reply.get("mode", mode)`): при откате PM на graceful агент видит `graceful`, а не запрошенный `force`. DESIGN этого не уточнял.

## Что осталось открытым / ненадёжным

- L6/L7 не запускались: нет окна стенда. Время стопа с зависшим ребёнком, предел (г) (kill только после join воркеров PM) и попадание строк в `system.log` живым прогоном не подтверждены.
- Цепочка логов собрана помощником Haiku. Я сам прочитал `log_paths.py`, `logger_core.py:773-782` и `system.log` в конфиге. Не проверены: точное имя каталога PM, правила scope, по которым модуль PM попадает в `system_file`, и захват stderr ребёнка через `capfd`.
- Предел (в) кодом не лечится: если `join_until` фазы 2 уже идёт со старым сроком, `force` его не сокращает. Записано в ADR.
- `doc-size-guard`: PM README 36.5 КБ, backend_ctl README 37.8 КБ, AGENTS.md 51.1 КБ, PM DECISIONS 247.8 КБ — всё выше бюджета 32 КБ. Превышение было до правки, файлы не делил (вне FILES).
- Поиск в памяти: `search.py shutdown force deadline kill --module process_manager_module` → `docs/claude/memory/project_graceful_stop_debt.md`. На решение не влияет.

## Решение лида по шагу 4 (применено)

`backend_ctl/driver.py:714-715`: при `accepted is False` ожидания нет — `pm_gone=False`, `elapsed_s` = время до ответа; докстринг :693-694. U+D: `20 passed, 1 warning in 2.48s`; ruff check rc=0, `1 file already formatted`; ручная проверка: ответ PM `{'error': 'deadline_s: 0.1..5.0'}` → `{'accepted': False, 'mode': 'force', 'elapsed_s': 0.0, 'pm_gone': False, 'outcomes': None}`. Отдельного теста на этот путь у тестера нет.
