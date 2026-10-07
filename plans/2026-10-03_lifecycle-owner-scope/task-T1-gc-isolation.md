# Task T1-iso — тесты механизма gc исполняются в своём интерпретаторе (вместо хелпера «вернуть заморозку»)

**Level:** Senior (teamlead, автор T1). **Родитель:** T1 (DONE `4c82e0167`, влит `a5ae9657a`). Хвост после слияния: CI Linux красный.

## Проблема и причина

`gc.freeze()` / `gc.unfreeze()` — глобальное состояние процесса. 26 тестов механизма (`process_module/tests/test_gc_collection_owner.py` — 19,
`test_gc_discipline.py` — 7) щёлкают настоящим рубильником внутри общего прогона pytest и размораживают сессионную кучу (~670 тыс. объектов):
следующая граница теста платит полной сборкой 170–282 мс. Хелпер `freeze_restored` (влит `0d6d031e5`/`70ba0e2f5`) пытается вернуть состояние
после каждого теста. Вернуть нельзя: `gc.get_freeze_count()` не монотонен (замороженный объект, умерший по refcount, уменьшает счётчик — на CI
Linux дельта −6, замер на 50 объектах: −51); на CPython 3.12 полный `gc.collect()` после `unfreeze` возвращает 377 объектов без `freeze`.
Допуск `abs(delta) < 100` (коммит `8f548b9d8`) прячет это. Причина — тесты трогают глобальное состояние родителя, а не то, что они его «неточно» возвращают.

## Решение

Тесты механизма идут в ОТДЕЛЬНОМ дочернем интерпретаторе (замер архитектора, Windows, CPython 3.12.12: 2.8 с на оба файла, куча ребёнка 136 тыс.
объектов, пауза границы в ребёнке ≤ 35 мс, у родителя счётчик заморозки 472 900 → 472 900). Боевой код не меняется. Хелпер и его тесты удаляются.
Это тот же шаблон, что `frontend_module/tests/test_qt_gc_policy.py` (subprocess, таймаут, `pytest.fail` при зависании).

## DESIGN

1. `process_module/tests/conftest.py`: `collect_ignore = ["test_gc_collection_owner.py", "test_gc_discipline.py"]` — единственный источник списка изолированных
   файлов; фикстура `own_interpreter_files` отдаёт их пути. Удалить: `freeze_restored`, `slot_suspended_freeze_restored`, `gc_slot_suspended`,
   `freeze_restore_block`, `slot_suspended_block`, ставшие ненужными импорты, поправить docstring модуля.
2. Новый `process_module/tests/test_gc_mechanism_own_interpreter.py::test_gc_mechanism_in_own_interpreter`: запуск
   `[sys.executable, "-m", "pytest", *files, "-q", "-rfE", "-p", "no:cacheprovider"]`, `cwd=` каталог `modules`, env `PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen`,
   `timeout=120`; `TimeoutExpired` → `pytest.fail`; проверки: `returncode == 0` (в сообщении хвост 30 строк вывода — имена упавших видны) и последняя
   строка итога начинается с литерала `"26 passed"`.
3. `test_gc_collection_owner.py` и `test_gc_discipline.py` вернуть к виду `1e647d579` (`git show 1e647d579:<путь>`): автофикстура
   `with _door().suspend_collection_owner(): yield`, в teardown `gc.unfreeze()`, в 4 тестах дисциплины `try/finally gc.unfreeze()`. Тела тестов не менять.
4. `tests/test_gc_policy_guard.py`, новое правило R4: тест-файл, вызывающий `gc.freeze`, `gc.unfreeze` или `suspend_collection_owner`, обязан быть в
   `collect_ignore` конфтеста своего каталога (читать `collect_ignore` AST-разбором `conftest.py`; второго списка не заводить). Выпадение имени из
   `collect_ignore` делает R4 красным: тесты молча вернулись бы в общий прогон, и паузы вернулись бы.
5. Удалить `process_module/tests/test_gc_freeze_restore.py` (тесты на хелпер, который удаляется). Правка `ci.yml` (`fetch-depth: 0` у job tests,
   коммит `8f548b9d8`) остаётся как есть.

## FILES

1. `multiprocess_framework/modules/process_module/tests/conftest.py`
2. `multiprocess_framework/modules/process_module/tests/test_gc_mechanism_own_interpreter.py` (новый)
3. `multiprocess_framework/modules/process_module/tests/test_gc_collection_owner.py`
4. `multiprocess_framework/modules/process_module/tests/test_gc_discipline.py`
5. `multiprocess_framework/modules/process_module/tests/test_gc_freeze_restore.py` (удалить)
6. `multiprocess_framework/modules/tests/test_gc_policy_guard.py`

## REDS (ожидаемые красные до реализации / на инъекциях)

- R1: внедрённая ошибка в тест любого из двух файлов → обёртка красная, имя упавшего теста в сообщении.
- R2: имя файла убрано из `collect_ignore` → красен R4 стража (файл вызывает `gc.unfreeze`, но не изолирован).
- R3: файл переименован или тест пропущен → в итоговой строке нет `26 passed` → обёртка красная.
- R4: синтетический тест-файл с `gc.unfreeze()` вне `collect_ignore` → одно нарушение R4.
- R5: обёртка зависла → `TimeoutExpired` → `pytest.fail` за 120 с, гейт не виснет.

## ACCEPTANCE

- `cd multiprocess_framework/modules && PYTHONUTF8=1 <venv>/python -m pytest process_module/tests -p no:cacheprovider -q --durations=0`: обёртка зелёная; в отчёте
  нет узлов двух изолированных файлов; teardown > 50 мс только у первой границы сессии.
- Счётчик заморозки родителя на вызове обёртки: сдвиг 0 (замер до/после).
- Явный запуск `pytest process_module/tests/test_gc_collection_owner.py` → `19 passed` в своём процессе (pytest не применяет `collect_ignore` к путям, названным явно).
- Ребёнок: `26 passed`, не дольше 3 с.
- Полный гейт `python scripts/gc_policy_acceptance.py gate -n 1`: 0 failed, 0 abort, нарушений gc 0, max пауза ≤ 250.
- Инъекции лида R1–R5 (прогноз до прогона, имена упавших после).

## Out of scope

Код T1 (`gc_discipline.py`, `qt_gc_policy.py`) и вариант «внедрить gc-бэкенд» (отвергнут: 45 вызовов `gc.*`, дублёр не знает про 377 бессмертных и падение
счётчика по refcount, всё равно нужен subprocess для 5 тестов). Проверка на Linux (только CI).

## Открыто

На Linux не проверено: `test_freeze_none_reads_flag` после `collect()` ожидает счётчик 0 — верно, пока в поколении 0 нет отслеживаемых бессмертных объектов;
на Windows воспроизведено, на Linux CPython 3.12 нет. `pytest-cov` не видит покрытие ребёнка без `COVERAGE_PROCESS_START`. В ребёнке остаётся ~0.64 с полных сборок
кучи 136 тыс. объектов — цена разморозки в процессе, который потом умирает.
