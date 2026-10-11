# lifecycle_guards — статические стражи жизненного цикла (G2, G6, G10)

План: `plans/2026-10-03_lifecycle-owner-scope/plan.md`, задача 0.5a. Только stdlib.

```
python -m scripts.lifecycle_guards check [--root PATH] [--only g2,g6,g10]
```

Строка на finding: `<guard> <rule> <path>:<line> — <message>`; итог:
`lifecycle-guards: N findings (G2 a, G6 b, G10 c); G2 pending: P; allowlist: E entries`.
Код 0 при N = 0, иначе 1. В гейт подключено: `scripts/validate.py` → `check_lifecycle_guards()`.

## Что стережёт

| страж | правило | что ловит |
|---|---|---|
| G2 | `signature` | строка `migrated`: `owner` не ключевой, с умолчанием или аннотация не ровно `IScope` (сравнивается текст) |
| G2 | `table-row` | «гнилая строка таблицы»: метода `путь::Класс.метод` нет в файле |
| G2 | `census` | `unlisted publisher`: производственное определение `subscribe`, `add_callback`, `add_change_callback`, `add_post_execute_callback`, `add_push_listener`, `add_tap`, `register_message_handler`, `register_handler` вне таблицы |
| G6 | `R1` | `Thread(`, `Timer(`, `ThreadPoolExecutor(` — только в `Plugins/` и `Services/` |
| G6 | `R2` | `QTimer(...)` без родителя (нет позиционных и `parent=`, либо первый позиционный или `parent=` — `None`) |
| G6 | `R3` | `.join(<число>)` или `.join(timeout=<число>)` |
| G6 | `R4` | `.terminate()` / `.kill()` без аргументов вне `child_process_stop.py` |
| G6 | `R5` | строка `"shutdown_timeout"` вне `stop_budget.py` |
| G6 | `R6` | `.deleteLater(...)` вне `qt_lifetime.py` |
| G6 | `R7` | импорт `base_manager.core.lifetime` вне `base_manager/` |
| G6 | `R8` | `lifetime.py` импортирует что-то кроме литерального списка task-0.2 |
| G6 | `R0` | файл не разбирается (`SyntaxError`): страж слеп к нему, поэтому finding |
| G10 | `shim` | маркер `lifecycle-shim:` в комментарии вне `SHIMS` или сверх разрешённого |
| G10 | `table-sum`, `table-row` | сумма `SHIMS` > 1; путь из `SHIMS` не существует («запись гнилая») |

Правила R1–R6 — только вызовы-методы/имена из AST: `kill()` как локальное имя (так `lifetime.py`
зовёт `res.kill` через `getattr`) не считается; строки в комментариях не считаются.

## Храповик G6

`ALLOWLIST` в `tables.py`: `(правило, путь) -> AllowEntry(count, reason)`. Больше `count` —
«новое нарушение»; меньше — «запись устарела, уменьши count»; путь исчез — «запись гнилая»;
`reason` короче 10 знаков или `count` <= 0 («запись мертва») — finding. Запись только уменьшается или удаляется; новая запись —
решение владельца. Таблицы — литералы; пути с `/`.

## Что считается производственным кодом

Все `.py`, кроме тех, у кого в пути на любом уровне каталог из `tests`, `testing`, `scripts`,
`.claude`, `docs`, `plans`, `workspace`, `examples`, или путь начинается с `backend_ctl/probes/`,
`robot/`, `tools/` (каталоги `tools/` внутри модулей — производственные), и кроме `test_*.py`,
`conftest.py`. Перечень: `git ls-files` (в worktree `.git` — файл, проверяется `exists()`),
вне git — `rglob` без `.venv`, `__pycache__`, `node_modules`.

## Пределы

- Обёртка совместимости без маркера `lifecycle-shim:` не видна G10.
- Файл, не отслеживаемый git (новый, ещё не `git add`), в перечень не попадает.
- Табличные записи G2/G6/G10 описывают наше дерево: на корне без `multiprocess_framework/modules`
  (`--root` чужого каталога, эвристика `has_repo_tables`) таблицы пусты, иначе каждая строка была бы
  «гнилой». Дыры в гейте нет: `scripts/validate.py` передаёт свой `BASE` — корень репозитория.
- G2 пропускает файлы, которые не разбираются (`SyntaxError`); G6 сообщает о них правилом `R0`.
- Псевдонимы не видны: `from threading import Thread as T`, `import threading as th`, `QTimer as Q`.
- Ссылка на метод без вызова не считается: `QTimer.singleShot(0, w.deleteLater)`, `connect(x.deleteLater)`.
- Исключения по ИМЕНИ файла в любом каталоге: `qt_lifetime.py` (R6), `child_process_stop.py` (R4),
  `stop_budget.py` (R5) — одноимённый файл в другом месте тоже освобождён.
- Это статика: поведение (abort-проба, плагин pytest) — задача 0.5b.

## Плагин и проба

Задача 0.5b. Динамические стражи G3 и G4 — pytest-плагин `pytest_plugin.py`; к нему проба abort
с живой осью — каталог `probe/`.

### Плагин G3/G4

Подключён ключом `-p scripts.lifecycle_guards.pytest_plugin` в `multiprocess_framework/modules/pytest.ini`
(`addopts`, плюс `pythonpath = ../..`: плагин `-p` импортируется раньше `conftest.py`, а при cwd = `modules`
корня в `sys.path` нет) и в `pyproject.toml` (`addopts`). На импорте только stdlib: ни `multiprocessing`,
ни `PySide6`, ни `base_manager` (`conftest.py` ставит `spawn` позже плагина).

| ручка | значения | умолчание | смысл |
|---|---|---|---|
| `LIFECYCLE_G3` | `off` / `report` / `fail` | `report` | в конце сессии `gc.collect()` и `base_manager.unclosed_roots()` |
| `LIFECYCLE_G4` | `off` / `report` / `fail` | `report` | поток, живой после теста, без `/` в имени (имя потока `spawn` — путь области) |

Неизвестное значение читается как `report`; в отчёте строка предупреждения с этим значением.
`report` код возврата не меняет; `fail` при N > 0 переводит успешный прогон в код 1 (красный тест
не маскируется ни в одном режиме). При `off`/`off` раздела отчёта нет; если выключен один страж,
раздел остаётся ради другого.

Формат отчёта (раздел `lifecycle-guards report` в конце сессии):

```
G3 unclosed roots: N
  <path> (open|abandoned)
G4 threads without scope path: N
  <nodeid> :: <имя потока>
```

G4: перепись `threading.enumerate()` до и после теста; новый живой поток подождали до 0,2 с на тест;
`MainThread` и `Dummy-*` не считаются.

### Проба abort

`python -m scripts.lifecycle_guards.probe axis [--runs 3] [--script PATH]` — ось жива, если репродуктор
(`probe/axis_chain.py`, копия отчёта CTO) в режиме `thread` падает во всех прогонах, а в режиме `main`
выживает (код 0 и `SURVIVED main`). Вывод: `axis: alive` / `axis: dead (...)` (код 0 / 2);
не `win32` без `--script` — `axis: unchecked (not win32)`.

`python -m scripts.lifecycle_guards.probe run [--mode offmain_gc] [--runs 3] [--targets ...] [--no-conftest]
[--cwd DIR] [--skip-axis] [--axis-script PATH]` — сначала ось (мёртвая ось: код 2, набор не запускается),
затем pytest с плагином `probe/crashprobe.py` `runs` раз. Исход прогона: `crashed` (в выводе
`Fatal Python error` / `access violation` либо код из `{134, 139, -6, -11, 3221225477, 3221225725,
3221226505}`), `not-triggered` (в журнале нет строки `at first logger test`), `failed` (иной ненулевой код;
код 3 pytest — `failed`), `survived`. Код 0 только при `survived == runs`. Подпроцессы пробы идут с
`LIFECYCLE_G3=off LIFECYCLE_G4=off`: проба меряет abort, а не стражей.

Замеры лида — `probe/baseline.json`. Прочтение: проба на реальном наборе слепа на этом дереве
(0 обёрток при T1; без T1 не падает); живая ось — `axis`.

### Пределы

- G4 видит только потоки без `/` в имени; поток с путём области, но живой после закрытия корня, ловит G3.
- G4 ловит поток, начатый внутри теста; поток, начатый в `conftest` вне теста, — нет.
- G5 (сборка мусора вне главного потока по `gc.callbacks`) в 0.5b не реализован — открытый вопрос О1.
- Проба на реальном наборе слепа: с T1 в наборе 0 обёрток Qt к первому тесту `logger_module`, нечему падать;
  доказательная сила — только при мёртвой/живой оси (`axis`) и 0 `not-triggered`.
- Ось проверена только на `win32` (offscreen и нативная платформа); на Linux — `unchecked`.
- `crashprobe.py` отличается от `docs/reviews/2026-10-03_task-5.5c-gate3/crashprobe.py.txt` двумя местами:
  журнал сбрасывается на диск после каждой строки; без загруженного `PySide6` проба молчит.

### Цены (О3)

Замер 2026-10-11, `frontend_module/tests` + `logger_module/tests`, cwd `multiprocess_framework/modules`,
`QT_QPA_PLATFORM=offscreen`, один прогон на вариант: без плагина (`-o addopts=`) 82,1 с; с плагином
(G3 и G4 `report`) 77,5 с — разница внутри разброса прогонов, измеримой цены нет. Записей G4 на этом
наборе: 0; корней G3: 0.
