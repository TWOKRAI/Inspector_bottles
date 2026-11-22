# Task 4a: отчёт developer (запуск сквозной проверки `letter_robot_sim`)

memory hits: `search.py chain check subprocess cleanup` -> 8 путей, по описаниям ни один не относится к задаче (консольные окна на Windows, гейт, тест рецепта); не использовались.
Перед первой правкой сообщение `DESIGN / FILES / starting edits` вверх не отправлял: правка не в `src/`, дизайн взят из брифа как есть.

## Что сделано

Файлы (все в `multiprocess_prototype/recipes/chain_checks/letter_robot_sim/`, папка не пакет, `__init__.py` нет):

- `chain_check.yaml` — структура и значения DESIGN п. 2 (`audit_cmd` записан блочным списком, содержимое то же).
- `run_chain_check.py` — шаги а–м DESIGN п. 3, вердикт п. 4, серия п. 5, коды п. 6. Только stdlib + `yaml`; клиент `backend_ctl.driver.BackendDriver` импортируется лениво и только при непустом `sim_commands` (в `sys.path` добавляется `--tree`). Шов для тестов: `main(argv, *, client_factory=None)`.
- `README.md` — запуск (в т. ч. `machine_gate.sh heavy`), порядок, чтение вердикта, переезд, раздел «Статусы этапов и будущий GUI» (4 строки, по рамке координатора).
- `tests/test_run_chain_check.py` — 36 тестов автора.
- Приёмочный `tests/test_run_chain_check_acceptance.py` не менял.

Решения там, где текст не договаривал:

- Группа процессов: каждый запущенный процесс в своей сессии (`start_new_session`), SIGTERM/SIGKILL уходит всей группе (потомки прототипа не остаются). Чужие процессы (другая сессия) не затрагиваются: проверено тестом (г).
- «Ответ без success»: настоящий ответ сима на `scene.defect_rate` — `{"status": "ok"}` (внутри `result`), поэтому успех = `success is True` или `status == "ok"` или `ok is True` в разобранном `result`. Исключение клиента, закрытое соединение, не-словарь — код 3.
- Падение/таймаут α: код 1, причина `alpha`, уборка и аудит идут дальше. Сборщик получает STOP после конца α и пересоздаётся каждые 0,5 с, пока не вышел (настоящий `collect.py` стирает «старый» STOP при старте; без пересоздания быстрая α давала бы ложный FAIL `сборщик`). Тест на это есть.
- Код 3 прерывает серию `--runs`; `verdict.md` при коде 3 не пишется, но `stages.json` и строка `СРЫВ` в `summary.md` есть. При FAIL серия продолжается.
- Код сборщика не входит в проверку (по тексту — «сборщик завершился»); печатается в `verdict.md` строкой «код сборщика».
- SIGTERM самому скрипту = Ctrl-C (уборка в `finally`), код 3.

### Дополнение лида: `stages.json`

`<out>/stages.json` рядом с `verdict.md`: 12 этапов с id из дополнения (`ports_free_before` … `verdict`), статусы `pending/running/pass/fail/skipped`, время `YYYY-MM-DD HH:MM:SS,mmm`, `note`; создаётся на старте с `pending`, обновляется через `stages.json.tmp` + `os.replace`, после упавшего шага остальные `skipped` (кроме `stop_processes`, он отражает уборку), `note` у `alpha` содержит строку `ТОЧНОСТЬ: …` дословно, `verdict` = pass/fail по МЕХАНИЗМУ. Формат `verdict.md` и `summary.md` не менялся. Ничего универсального сверх этого не добавлял.
Следствие: каталог `run1` теперь создаётся и при занятом порте до старта (там лежит `stages.json` с `ports_free_before: fail`).

## Прогон (через `machine_gate.sh light simaudit-inspector-bottles-ee`, `.venv/bin/python`, `PYTHONPATH=<worktree>`)

Импорт доказан из того же cwd: `multiprocess_framework.__file__` = `/Users/twokrai/Project_code/Inspector_bottles--lane-sim-audit/multiprocess_framework/__init__.py` (внутри worktree).

| набор | результат |
|---|---|
| приёмочный (слепой tester), первый прогон | 77 passed, 0 failed (64,85 с) |
| оба файла после `stages.json` | 113 passed, 0 failed (81,06 с): 77 приёмочных + 36 автора |
| `ruff check` по папке | All checks passed |
| `ruff format --check` моих файлов (`run_chain_check.py`, `tests/test_run_chain_check.py`) | чисто |
| `git grep --no-index -n "import scripts.alpha_sim\|from scripts.alpha_sim\|from scripts import alpha_sim" -- …/run_chain_check.py` | exit 1 (без `--no-index` файл неотслеживаемый, и exit 1 был бы пустым; считаю по `--no-index`) |
| после прогонов `ps` по `fake.py` | 0 живых |

## Подозрения на неверные тесты

Падений нет, подозрений на логику нет. Одно замечание по форме: `ruff format --check` красный на **приёмочном файле** (`test_run_chain_check_acceptance.py`: `r'''` вместо `r"""` и один перенос тернарника; не правил по запрету). Если гейт требует format-clean по папке, лид или tester форматирует его.

## Инъекции (мои, откатом одной правки; файл восстановлен `cp`, `diff` пуст)

| правка | красные |
|---|---|
| A: убрана уборка в `finally` (`forced = []`) | 44 красных из 113 (все (е), (м), (б), (в), (г), (и), отдельные (з),(л),(н) и 10 моих), т. е. сильный сигнал |
| B: команды сима после запуска сборщика | 6: мой `test_sim_commands_go_out_before_collector...`, 4 моих `test_rejected_sim_command...`, приёмочный `test_l_failed_sim_command_stops_before_collector_and_alpha` |
| C: STOP сборщику сразу после его запуска (до α) | 2: `test_n_stop_file_does_not_exist_while_alpha_is_running`, `test_n_collector_sees_stop_only_after_alpha_has_finished` |
| D: проверка портов после остановки всегда «свободны» | 1: `test_d_foreign_listener_after_stop_gives_exit_1_and_reason_ports` |
| F: без SIGKILL | 2: приёмочный `test_cleanup_sends_sigterm_first_then_sigkills...` и мой `test_cleanup_stops_two_real_subprocesses...` |
| G: `stages.json` пишется напрямую вместо tmp + `os.replace` | красный `test_stage_log_is_created_all_pending_and_never_seen_torn_by_a_reader` (656+ битых чтений) |

Инъекции A–F шли до добавления `stages.json` (числа на 104 тестах: 77 + 27), G — после.

## Что я оставил открытым / ненадёжным

- Живого прогона не было (запрещён): реальный `BackendDriver.connect(timeout=…)`/`send_command(…, timeout=…)` против настоящего сима не проверен, только фейк-клиент; сигнатуры сверил по `backend_ctl/driver.py`/`interfaces.py`. Форма «ответа без success» выведена из `cmd_defect_rate` и `run_alpha._ok`, не из живого ответа.
- Порядок «сборщик запущен до α» проверяется слабо (то же, что писал tester): `Popen(collector)` и `Popen(α)` идут подряд, различить порядок по меткам на гонке нельзя; код гарантирует порядок строками последовательно.
- Windows: ветка без групп (`CREATE_NEW_PROCESS_GROUP`, `terminate/kill` только лидера) не тестировалась; потомки прототипа там могут пережить уборку. Тесты POSIX-only.
- Проверка «порт свободен» — TCP-подключение к 127.0.0.1; слушатель только на другом интерфейсе или IPv6 не видится. `lsof` для «кто занял» может отсутствовать (тогда в тексте «нет lsof»); в тестах не проверялся.
- Риск повторного использования pid: после смерти лидера группа проверяется `killpg(pid, 0)`; окно крайне малое, но не ноль.
- Сборщик, вышедший с ненулевым кодом (например, 2 «каталог уже содержит данные»), вердикт не валит, только печатает код; провал виден лишь через аудит. Если нужно считать это причиной `сборщик`, это правка одной строки и решение лида.
- Таймаут аудита 300 с — константа в коде, в конфиге такого ключа нет (DESIGN не давал).
- `KeyboardInterrupt` на шагах а–е/з даёт код 3 без `verdict.md`; прерывание на шаге α отдельно не обрабатывается.
- Формат слов `{words}` — через запятую (по README аудита), запись в `chain_check.yaml` не проверена на живом аудите.
- Приёмочный файл не format-clean (см. выше).
- Тесты автора на живых фейках занимают порты, выбранные через bind на порт 0 (гонка между освобождением и повторным использованием теоретически возможна, на практике не наблюдалась).
