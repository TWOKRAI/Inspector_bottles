# Task 5.5d — Qt-мусор собирается на главном потоке; тесты не оставляют потоков batch-drain

**План:** [`plan.md`](plan.md) · фаза 5 — [`phase-5.md`](phase-5.md). Продолжение 5.5c: гейт `/dev:ship` не должен краснеть случайно.
**Level:** Middle (тестовая инфраструктура) · **Assignee:** лид (реализация соло — 2–3 тестовых файла, < 80 строк, прод-код не меняется), tester (слепой, worktree на main до правки), reviewer · **Layer:** tests

**Основание:** диагноз investigator 2026-10-03, OPEN_QUESTIONS §5.5c п.8.
- `run_framework_tests.py` упал 1 раз из 3: `Fatal Python error: Aborted` → `access violation`.
- Механизм: тесты `frontend_module` оставляют циклический мусор из `QWidget` (103 недостижимых виджета перед `logger_module`). Сборщик иногда разбирает его на неглавном потоке. Shiboken откладывает удаление на главный поток (`delete-in-main-thread`), и процесс падает.
- Воспроизведение: зонд `docs/reviews/2026-10-03_task-5.5c-gate3/crashprobe.py.txt`, `CRASHPROBE_MODE=offmain_gc` — 3 падения из 3. Сборка на главном потоке — 0 из 2.
- Усилитель — 6 потоков `batch-drain`: тесты `channel_routing_module/observability/tests/test_task_3_3_store_tap_batch_acceptance.py` не зовут `close()`.

**Ветка:** `fix/t55d-qt-gc` от main, своя worktree. Сливается в main напрямую, затем main вливается в `feat/transport-f5`.

**Files:**
- `multiprocess_framework/modules/conftest.py` — две autouse-фикстуры;
- `multiprocess_framework/modules/channel_routing_module/observability/tests/test_task_3_3_store_tap_batch_acceptance.py` — закрытие воркеров;
- новый тест tester'а `multiprocess_framework/modules/tests/test_t55d_qt_gc_and_thread_leaks.py`.

Прод-код не меняется.

**DESIGN:**
1. **Сборка Qt-мусора на главном потоке.** Autouse-фикстура `scope="module"`. На teardown модуля она вызывает `gc.collect()`, если в `sys.modules` есть `PySide6.QtWidgets`. Причина: мусор собирается на главном потоке раньше, чем до него доберётся сборка на чужом. Контроль investigator — 0 падений из 2.
2. **Страж утечки потоков `batch-drain-*`** — по образцу `_no_leaked_state_flushers` (`modules/conftest.py:117`).
   - Сравнивается множество потоков до и после теста, а не их число.
   - Краснеет только тест, который добавил живой поток.
   - Утёкший поток гасится best-effort до fail.
3. **Тестовый файл 3.3:** фикстура, которая зовёт `close()` у каждого созданного `BatchDrainWorker`.

**Acceptance criteria:**
- [ ] (tester) Падение лечится, проверка по процессу целиком. Подпроцесс `python -m pytest -p multiprocess_framework.modules.conftest <tmp>`, где `<tmp>` содержит два модуля:
  - модуль A создаёт ≥ 20 `QWidget` без родителя в ссылочных циклах (`w.self_ref = w`) и удаляет имена;
  - модуль B первым тестом вызывает `gc.collect()` в отдельном `threading.Thread` и ждёт `join`, затем создаёт `QWidget`.

  Ожидание: код возврата 0, `2 passed`. `QT_QPA_PLATFORM=offscreen`, `QApplication.instance() or QApplication([])`.
- [ ] (tester) Контроль живости оси: тот же запуск без `-p multiprocess_framework.modules.conftest` → код возврата ≠ 0 и в выводе `Fatal Python error`. Если контроль не падает, тест сообщает «ось не живая», а не зелёный.
- [ ] (tester) Страж потоков: подпроцесс с `-p multiprocess_framework.modules.conftest`.
  - Тест создаёт `BatchDrainWorker` (`channel_routing_module/observability/batch_drain.py`) и не зовёт `close()` → прогон красный, в выводе `batch-drain`.
  - Тот же тест с `close()` → зелёный.
- [ ] (tester) После прогона `test_task_3_3_store_tap_batch_acceptance.py` целиком (подпроцесс) живых потоков с именем `batch-drain-*` нет. Проверяет финальный тест в том же подпроцессе, через `threading.enumerate()`.
- [ ] (лид) Зонд `CRASHPROBE_MODE=offmain_gc` на `frontend_module/tests frontend_module/graph/tests logger_module/tests/test_channels_extra.py logger_module/tests/test_console_backpressure.py`:
  - до правки — 3 падения из 3;
  - после — 0 из 3.
- [ ] (лид) `python scripts/run_framework_tests.py` ×3: 0 failed, 0 аварийных завершений. Длительность не больше +10 % к 720–864 с (цена `gc.collect()` на модуль) — числа в отчёте.
- [ ] (лид) Корневой `pytest -q` ×1: 0 failed.

**Инъекции (лид):**
- фикстура (1) снята → тест A/B красный;
- страж (2) снят → тест стража красный;
- `close()` в файле 3.3 снят → страж красный на этом файле.

**Out of scope:**
- прод-риск сборки Qt-мусора в живом GUI — вопрос CTO на приёмке фазы (OPEN_QUESTIONS §5.5c п.8);
- поиск тестов, которые создают виджеты без `qtbot.addWidget`.
