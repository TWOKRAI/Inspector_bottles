# gui-graceful-close, задача 1.2a: отчёт teamlead (стадия 2, GREEN)

Дерево: `.claude/worktrees/op-1.2a`, ветка `feat/gui-close-1.2a`, база `392cd392d` (слепой набор tester). Ничего не
закоммичено. Сообщение коммита: `docs/reviews/2026-11-07_gui-graceful-close_task-1.2a-teamlead.commitmsg.txt`.
memory hits: `scripts/memory/search.py supervision status stop phase store --module process_manager_module` ->
`feedback_unblocking_signal_at_the_moment_of_fact.md` (учтено: `done` ставится в момент факта `join_until == True`),
`project_graceful_stop_debt.md`, `project_industrial_standards_packml.md` (не относятся).

## 1. Что сделано

Файл `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`:

1. Константы модуля: `_SYSTEM_STOP_PHASES`, `_SYSTEM_STOP_STORE_KEYS`, `_SHUTDOWN_SENDER_KEY = "_sender"`.
2. Класс-уровневые дефолты `_system_stop_info: dict | None = None` и `_system_stop_published: dict | None = None`
   (образец `_children_stopping`). Два листовых лока: создаются в `__init__` и запасным путём
   `self.__dict__.setdefault(...)` в свойствах `_system_stop_lock` / `_system_stop_publish_lock`.
3. Помощники после `_pm_stopping`: `_system_stop_snapshot` (копия под локом), `_begin_system_stop` (первый
   выигрывает, бюджет читается до лока), `_escalate_system_stop`, `_set_system_stop_phase` (`None` — WARNING без
   словаря; `done` конечная), `_set_pre_stop_step`, `_publish_system_stop` (под publish-локом: текущий снимок, только
   изменившиеся ключи, `try/except` вокруг каждого `handle_state_set`, `None`-стор — выход).
4. `_cmd_system_shutdown`: инициатор из `args["_sender"]`; `begin` после проверки аргументов и `set_force_deadline`,
   ДО взвода событий; при `False` от `begin` и принятом force — `_escalate_system_stop`; публикация — после событий.
5. `_cmd_supervision_status`: верхнее поле `system_stop` (копия); при `None` и `_pm_stopping()` — ленивый
   `_begin_system_stop("graceful", "event", None)`. Ленивый begin в стор не пишет (чтение; стор пишет `request_stop`).
6. `_handle_process_command`: только для `cmd == "system.shutdown"` — `inner_msg["data"]["_sender"] = msg.get("sender")`.
   Остальным командам `data` не меняется.
7. `_ChildrenStop`: новый `_announce_phase(phase, begin=False)` (begin как `event` при необходимости + фаза + публикация,
   сбой — ERROR в лог). Вызовы: первая строка `request_stop` (до `pm._children_stopping = True`); `join_until` — `done`,
   если группа вернула `True`; `close()` — `done` в `finally` после `group.close()`.

Документы: ADR-PMM-041 в `process_manager_module/DECISIONS.md` (номер свободен: 042 у Task 1.2); абзац о `system_stop`
в `process_manager_module/README.md` (после таблицы команд); строка `supervision_status` в `backend_ctl/AGENTS.md:145`.
`python -m scripts.sync` переписал одну строку `multiprocess_framework/DECISIONS.md` (`ADR-PMM-001…041`).

Новый файл: `multiprocess_framework/modules/process_manager_module/tests/test_supervision_status_system_stop_hazards.py`
(H9 — 1 тест, H10 — 2 случая: `slow-children-write`, `late-children-publisher`).

## 2. Решения а)–ж)

| | Решение лида | Как реализовано |
|---|---|---|
| а | `msg["sender"]` верхнего уровня; пусто/None/нет -> `unknown` | `_handle_process_command` кладёт `msg.get("sender")` в `data["_sender"]`; `_cmd_system_shutdown`: `args.get("_sender") or "unknown"`, не `str` -> `unknown` |
| б | `deadline_at` в `time.time()` для обоих режимов | `started_at = time.time()`; `deadline_at = started_at + window_s`; эскалация `time.time() + deadline_s` |
| в | первый force: `mode == "force"`, `now + deadline_s` | `_begin_system_stop("force", initiator, deadline_s)` при `set_force_deadline == True` |
| г | 4 дельты в любом порядке, пятая `done` | порядок публикации `phase, mode, initiator, started_at`, затем `done` |
| д | без стора `system_stop` заполняется | `_publish_system_stop` выходит при `ssm is None`; словарь пишется до публикации |
| е | после `join_until == False` и kill — не `done`; `done` в `close()` | `join_until` ставит `done` только при `True`; `close()` — в `finally` |
| ж | `phase=children` в стор до исполнителя, первым действием, до `_children_stopping` | `_announce_phase("children", begin=True)` — первая строка `request_stop` |

## 3. Прогоны

Путь импорта (из cwd pytest, `PYTHONPATH=<дерево>`):
`/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.2a/multiprocess_framework/__init__.py`.

| Что | Команда (через `machine_gate.sh`) | Итог |
|---|---|---|
| слепой набор S | `light op-1.2a … pytest -q tests/test_supervision_status_system_stop.py` | `34 passed in 9.89s` (первая итерация) |
| авторский H | `light op-1.2a … pytest -q tests/test_supervision_status_system_stop_hazards.py` | `3 passed in 0.63s` |
| весь каталог PM | `medium op-1.2a … pytest -q --tb=short multiprocess_framework/modules/process_manager_module/tests` | `6 failed, 1576 passed, 1 skipped, 1 xfailed in 428.87s`; красные — 6 `test_cv_threads.py` (ожидаемые, красные и на чистом main по брифу); `test_backend_ctl_socket_*` в этот прогон зелёные |
| страж golden | `light … process_module/tests/test_process_root_acceptance.py::test_root_close_order_golden` | `1 passed` |
| ruff | `ruff check -q process_manager_module/`; `ruff format --check` двух файлов | чисто, rc=0 |
| `scripts/validate.py` | из дерева | 3 FAIL: теги памяти, индекс `BY-MODULE*.md`, `G6 R6 multiprocess_prototype/frontend/shutdown/close_coordinator.py:95`. Ни один путь не входит в мой дифф; на чистом main не сверял (см. раздел 6) |

## 4. Инъекции

Патчи — на копии дерева в scratchpad (`inj_tree`, файлы `multiprocess_framework`, `scripts`, `conftest.py`,
`pyproject.toml`); рабочее дерево не откатывалось. Скрипт:
`/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/e2edcaee-7aad-4901-9110-64aff4d27ddb/scratchpad/run_inj.py`
(каждый якорь проверен `count == 1`; нет строки итога pytest — скрипт падает). Лог:
`/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/e2edcaee-7aad-4901-9110-64aff4d27ddb/scratchpad/inj.log`.
Запуск: `machine_gate.sh heavy op-1.2a … run_inj.py`. Наборы — S + H (37 случаев); для I8 ещё
`test_process_manager_process.py`, `test_supervision_instance_truth.py`, `test_system_shutdown_force.py`.
Чистая копия после матрицы: `37 passed`.

Первый запуск матрицы дал «0 красных» у всех инъекций: в копии не было `scripts/` (плагин `lifecycle_guards`),
pytest не стартовал. Скрипт не проверял строку итога. Исправлено (копия `scripts/`, `assert tail`), матрица перезапущена.
Результат первого запуска недействителен.

| № | Что ломаем | Предсказано | Наблюдено | Сверка |
|---|---|---|---|---|
| I1 | нет `begin` в `request_stop` | S3, S6, S7 | S3[after-request-stop], S7 | **расхождение по S6**: в S6 стоп начинает команда (`begin` в `_cmd_system_shutdown` до событий), `begin` из `request_stop` на этом пути не работает — 5 дельт остаются. Предсказание исходило из того, что `begin` только в `request_stop`. Путь «событие без команды» держат S3 и S7 |
| I2 | `done` в `_stop_summary` | S8 | S8 (2 случая), S8b, S8c | совпало + |
| I3 | не публиковать в стор | S6, S8 | 10: S3[after], S6, S6a, S6b[raises], S7, S8 (2), S8c, H10 (2) | совпало + |
| I4 | force без `deadline_s` | S4 | S4: force-0.5, force-3.0-budget-8, force-lower-bound, force-default | совпало; `force-upper-bound` зелёный: 5.0 совпадает с бюджетом graceful 5.0 (так же у tester) |
| I4b | эскалация без `deadline_at` | S5 | S5 | совпало |
| I5 | нет эскалации | S5 | S5, S6a | совпало + |
| I6 | `children` после `_stop_lifecycle_executor` | S7 | S7 | совпало |
| I7 | `sender` не доставляется | S2 | S2 (gui, backend_ctl), S2c, S5, S6 | совпало + |
| I8 | дефолт `_system_stop_info` в `__init__` | S1 + перечисленные | 46 красных: S1 (bare, light) и все лёгкие S, H (3), `test_process_manager_process.py` (5, в т.ч. 3 `supervision_status`), `test_supervision_instance_truth.py` (7), `test_system_shutdown_force.py` (9) | совпало + |
| I9 | снимок без копии под локом | H9 | H9 | совпало; ловит детерминированно (снимки до эскалации должны остаться `graceful`) |
| I10a | публикация без `_system_stop_publish_lock` | H10 | H10[slow-children-write] | совпало |
| I10b | значение фазы из аргумента издателя | H10 | H10[late-children-publisher] | совпало; каждый вариант ловит ровно один случай H10 |
| I11 | нет ленивого `begin` в status | S3 | S3[before-request-stop] | совпало |
| I12 | `begin` до проверки аргументов | S2 | S2d (3), S2 (2), S2c, S5, S6 | совпало +: ранний `begin` с `unknown` выигрывает у команды |
| I13 | `done` на любом возврате `join_until` | S8 | S8[child-needs-terminate], S8c | совпало |

## 5. ESCALATION

Нет. Красных тестов tester, которые я считаю неверными, нет: 34 из 34 зелёные без правки тестов.

## 6. Что осталось открытым / ненадёжно

- **Windows не запускался.** Пункт heavy (граф `inspection_full`, опрос 100 мс видит `children`, `done` дельтой стора)
  ждёт стенда.
- **Проба Mac `probe_slow.py` с чтением `system_stop` не запускалась.** Пункт ACCEPTANCE «≥ 20 ответов `children`,
  `initiator == "backend_ctl"`» не проверен мной; его проверяет лид пробой.
- **Живой путь GUI `router.request` не проверен.** Инициатор берётся из `sender` верхнего уровня конверта; что GUI
  кладёт туда имя своего процесса (`command_sender.py:220`), я не проверял запуском. Слепой набор строит конверт
  `build_system_command_message` и вызывает `_handle_process_command` напрямую.
- **Служебный ключ `_sender` можно подставить.** Прямое `send_command(pm, "system.shutdown", {"_sender": "x"})` мимо
  конверта даст `initiator == "x"`. Конверт `process.command` ключ перекрывает. Для наблюдаемости это допустимо, для
  аудита — нет.
- **Ленивый `begin` в `supervision.status` в стор не пишет.** Стор узнаёт о стопе по событию при `request_stop`. Окно
  «status видит стоп, стор ещё нет» существует (до `request_stop`).
- **`_system_stop_publish_lock` не полностью листовой:** под ним идёт `handle_state_set` (локи SSM). Так задано DESIGN
  (он сериализует публикации). Публикация не зовётся под `_ChildrenStop._lock` и под локом словаря; проверено чтением
  трёх мест вызова, не тестом на взаимоблокировку.
- **H9 ловит «снимок без копии», а не «копия без лока».** Разрыв пары `mode`/`deadline_at` при чтении без лока GIL почти
  не открывает; такая инъекция не прогонялась — «не покрыто».
- S6 при нуле детей (сколько дельт) не проверен ни tester, ни мной.
- Документы сверх бюджета размера (предупреждение хука, не от этой правки): `process_manager_module/DECISIONS.md`
  306 КБ, `README.md` 39,5 КБ, `backend_ctl/AGENTS.md` 51 КБ.
- `scripts/validate.py`: те же 3 FAIL на чистой базе `392cd392d` (временное дерево, затем удалено) — не мои.
- В `.commitmsg.txt` строка `Co-Authored-By: Claude Opus 5.5` — по атрибуции среды (исполнитель — Opus 5.5), а не
  `Sonnet 5.5` из брифа. Лид решает при коммите.
- `test_backend_ctl_socket_*` в этот прогон зелёные; на чистом main отдельно не сверял (сверять было нечего).
