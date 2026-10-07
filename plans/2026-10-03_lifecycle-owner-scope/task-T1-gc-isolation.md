# Task T1-iso — тесты механизма gc исполняются в своём интерпретаторе (вместо хелпера «вернуть заморозку»)

**Level:** Senior (teamlead, автор T1). **Родитель:** T1 (DONE `4c82e0167`, влит `a5ae9657a`). Хвост после слияния: CI Linux красный.
**Редакция 2** (ревью спека р1: CHANGES REQUESTED, 8 пунктов — учтены ниже).

## Проблема и причина

`gc.freeze()` / `gc.unfreeze()` — глобальное состояние процесса. 26 тестов механизма (`process_module/tests/test_gc_collection_owner.py` — 19,
`test_gc_discipline.py` — 7) щёлкают настоящим рубильником внутри общего прогона pytest и размораживают сессионную кучу (~670 тыс. объектов):
следующая граница теста платит полной сборкой 170–282 мс. Хелпер `freeze_restored` (влит `0d6d031e5`/`70ba0e2f5`) пытается вернуть состояние
после каждого теста. Вернуть нельзя: `gc.get_freeze_count()` не монотонен (замороженный объект, умерший по refcount, уменьшает счётчик — на CI
Linux дельта −6, замер на 50 объектах: −51); на CPython 3.12 полный `gc.collect()` после `unfreeze` возвращает 377 объектов без `freeze`.
Допуск `abs(delta) < 100` (коммит `8f548b9d8`) прячет это. Причина — тесты трогают глобальное состояние родителя, а не то, что они его «неточно» возвращают.

## Решение

Тесты механизма идут в ОТДЕЛЬНОМ дочернем интерпретаторе (замер, Windows, CPython 3.12.12: стенные часы подпроцесса 2.70–2.85 с на оба файла, куча ребёнка
136 тыс. объектов, пауза границы в ребёнке ≤ 35 мс). Боевой код не меняется. Хелпер и его тесты удаляются. Тот же шаблон, что
`frontend_module/tests/test_qt_gc_policy.py` (subprocess, таймаут, `pytest.fail` при зависании).

## DESIGN

1. `process_module/tests/conftest.py`: `collect_ignore = ["test_gc_collection_owner.py", "test_gc_discipline.py"]` — единственный источник списка изолированных
   файлов (литерал); фикстура `own_interpreter_files` отдаёт их абсолютные пути. Удалить: `freeze_restored`, `slot_suspended_freeze_restored`, `gc_slot_suspended`,
   `freeze_restore_block`, `slot_suspended_block`, ставшие ненужными импорты, поправить docstring модуля.
2. Новый `process_module/tests/test_gc_mechanism_own_interpreter.py::test_gc_mechanism_in_own_interpreter`:
   - `files = own_interpreter_files`; `assert files` (непустой) и `assert all(p.is_file() for p in files)` — иначе `pytest` без путей собрал бы весь каталог, включая саму обёртку (рекурсия);
   - защита от рекурсии: если в окружении есть `FW_GC_OWN_INTERPRETER_CHILD`, `pytest.fail`; ребёнку env это выставляет;
   - запуск `[sys.executable, "-m", "pytest", *files, "-q", "-rfE", "-p", "no:cacheprovider"]`, `cwd=` каталог `modules`, env `dict(os.environ, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen", FW_GC_OWN_INTERPRETER_CHILD="1")` (НЕ заменять env целиком: без `PATH` INTERNALERROR), `timeout=120`;
   - `TimeoutExpired` → `pytest.fail` с хвостом вывода;
   - проверки: `returncode == 0` (в сообщении хвост 30 строк вывода — имена упавших видны) и итоговая строка (последняя непустая) `startswith("26 passed")` — строка может быть «26 passed, 1 warning in …».
3. `test_gc_collection_owner.py` и `test_gc_discipline.py` вернуть к виду `1e647d579` (`git show 1e647d579:<путь>`): автофикстура
   `with _door().suspend_collection_owner(): yield`, в teardown `gc.unfreeze()`, в 4 тестах дисциплины `try/finally gc.unfreeze()`. Тела тестов не менять.
4. `tests/test_gc_policy_guard.py`, новое правило R4 (AST, без allowlist): ни один файл под `tests/`-каталогами (включая `conftest.py` и хелперы) не вызывает `gc.freeze`,
   `gc.unfreeze`, `suspend_collection_owner` — кроме файлов, чьё имя стоит в `collect_ignore` соседнего `conftest.py` (читается AST-разбором; `collect_ignore` не литерал
   списка строк → нарушение). Сканер ловит формы: `gc.unfreeze()`, `import gc as g; g.unfreeze()`, `from gc import freeze/unfreeze` (и `as`), `getattr(gc, "unfreeze")()`,
   присваивание `f = gc.unfreeze`, `suspend_collection_owner` как `Name` и как `Attribute` (`_door().suspend_collection_owner()`). Вывод нарушений — `путь:строка`.
   **Интерфейс (контракт для слепого тестера; живёт в `test_gc_policy_guard.py`, импорт `from multiprocess_framework.modules.tests import test_gc_policy_guard as g`):**
   `g.isolated_names(conftest_source: str) -> frozenset[str]` — имена из литерала `collect_ignore` (список строк), иначе `ValueError`;
   `g.r4_violations(path: str, source: str, isolated: frozenset[str]) -> list[str]` — `path` от корня репо (POSIX), `isolated` — имена соседнего `conftest.py`;
   результат — список строк `"<path>:<line>"` (пустой, если нарушений нет или `basename(path)` ∈ `isolated`; `conftest.py` никогда не изолирован).
   **Решения по неоднозначностям (после слепой приёмки, лид):** `collect_ignore` отсутствует в конфтесте → `frozenset()` (каталог без изоляции — норма); пустой `[]` → `frozenset()`;
   кортеж или список строк — допустимы; присвоение не литерала (имя, вызов, генератор, нестроковый элемент) → `ValueError`. `from gc import freeze/unfreeze [as x]` — одно нарушение на
   строке вызова; сам `import` без вызова нарушением не считается (тест тестера допускает любую из двух строк, реализация берёт строку вызова). Порядок результата — по возрастанию строки.
   Случаи R4 — в synthetic-тестах (как у R1–R3 того же файла). Выпадение имени из `collect_ignore` делает R4 красным (в двух файлах 8 и 4 прямых вызова).
5. Удалить `process_module/tests/test_gc_freeze_restore.py` (тесты на хелпер, который удаляется; свойства хелпера снимаются осознанно вместе с ним). Правка `ci.yml`
   (`fetch-depth: 0` у job tests, коммит `8f548b9d8`) остаётся как есть.

## FILES

1. `multiprocess_framework/modules/process_module/tests/conftest.py`
2. `multiprocess_framework/modules/process_module/tests/test_gc_mechanism_own_interpreter.py` (новый)
3. `multiprocess_framework/modules/process_module/tests/test_gc_collection_owner.py`
4. `multiprocess_framework/modules/process_module/tests/test_gc_discipline.py`
5. `multiprocess_framework/modules/process_module/tests/test_gc_freeze_restore.py` (удалить)
6. `multiprocess_framework/modules/tests/test_gc_policy_guard.py`

## REDS (ожидаемые красные на инъекциях)

- R1: внедрённая ошибка в тест любого из двух файлов → обёртка красная, имя упавшего теста в сообщении.
- R2: имя файла убрано из `collect_ignore` → красен R4 стража (файл вызывает `gc.unfreeze`, но не изолирован).
- R3: файл переименован или тест пропущен → итоговая строка не начинается с `26 passed` → обёртка красная.
- R4: synthetic-файлы с каждой из форм вызова (см. DESIGN 4) вне `collect_ignore` → по одному нарушению с `путь:строка`; `conftest.py` с `gc.unfreeze()` → нарушение.
- R5: обёртка зависла → `TimeoutExpired` → `pytest.fail` за 120 с, гейт не виснет.
- R6: `collect_ignore` пуст → `assert files` красный (без рекурсии).

## ACCEPTANCE

- `cd multiprocess_framework/modules && PYTHONUTF8=1 <venv>/python -m pytest process_module/tests -p no:cacheprovider -q --durations=0`: обёртка зелёная; в отчёте нет узлов
  двух изолированных файлов; паузы gc родителя — по строке `gc-policy` (max_pause не больше базы, нарушений 0); список teardown > 50 мс не шире базы на том же прогоне
  (замер лида, не assert: `test_t52` даёт 0.06 с без связи с gc).
- Родитель не затронут — замер лида (не assert): объект-часовой, замороженный ДО вызова обёртки, после вызова не виден в `gc.get_objects()`; счётчик заморозки как
  справка, не как условие (он немонотонен).
- Явный запуск `pytest process_module/tests/test_gc_collection_owner.py` → `19 passed` (pytest не применяет `collect_ignore` к путям, названным явно).
- Ребёнок: `26 passed`; стенные часы подпроцесса — замер лида (2.70–2.85 с), не assert; assert только `timeout=120`.
- Job `tests` в GitHub Actions на коммите задачи зелёный (ссылка на run в отчёте) — до этого задача не считается закрытой; Linux локально не проверяется.
- Полный гейт `python scripts/gc_policy_acceptance.py gate -n 1`: 0 failed, 0 abort, нарушений gc 0, max пауза ≤ 250.
- Инъекции лида R1–R6 (прогноз до прогона, имена упавших после).

## Решения (приняты по ревью спека)

- **Покрытие.** `make test` (pytest-cov, локально) не увидит покрытие ребёнка: `gc_discipline.py` в отчёте покажет меньше. Принято осознанно: CI покрытие не измеряет
  (`run_framework_tests.py` без `--cov`), а `integrator` — совещательный; поведение тестами по-прежнему проверяется. Сбор покрытия ребёнка (`COVERAGE_PROCESS_START`) — не делаем.
- **Out of scope:** код T1 (`gc_discipline.py`, `qt_gc_policy.py`) и вариант «внедрить gc-бэкенд» (отвергнут: 45 вызовов `gc.*`, дублёр не знает про 377 бессмертных и падение
  счётчика по refcount, всё равно нужен subprocess для 5 тестов). Проверка на Linux — только CI.

## Открыто

- На Linux не проверено: `test_freeze_none_reads_flag` после `collect()` ожидает счётчик 0 — верно, пока в поколении 0 нет отслеживаемых бессмертных объектов; на Windows
  воспроизведено, на Linux CPython 3.12 нет. `sys.executable` в uv-venv на Linux не проверен.
- Путь размораживания, который R4 не видит: повторный `install_gui_memory_policy(None)` в процессе родителя размораживает кучу (замер ревьюера: счётчик 117030 → 0). Запретить
  вызов нельзя (сессионный `modules/conftest.py` ставит политику на старте); защищён только вызовами `gc.*`/`suspend`.
- На Windows `subprocess.run(timeout)` после kill вызывает `communicate()` и может повиснуть, если пайп держит внук; в двух файлах `subprocess`/`multiprocessing` нет, сегодня R5
  выполняется, как гарантия не принимается. `PYTEST_ADDOPTS` родителя наследуется ребёнком — итог тогда громко красный.
- В ребёнке остаётся ~0.64 с полных сборок кучи 136 тыс. объектов — цена разморозки в процессе, который потом умирает.
