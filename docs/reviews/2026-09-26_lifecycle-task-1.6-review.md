# Ревью Task 1.6 (lifecycle-stop-ownership) — итерация 1

**Ревьюер:** reviewer (Opus), синхронно · **Ветка:** `fix/lifecycle-1.6` @ a19dc68d · **Дата:** 2026-09-26
**Вердикт:** REQUEST_CHANGES (итерация 1 из 2). Записано ведущим дословно по отчёту ревьюера (роль без записи файлов).

## Прогнано ревьюером

- `test_stop_summary_hazards.py` — 6 passed; `test_stop_summary_live.py --backend-live` — 3 passed.
- `test_system_shutdown_live.py --backend-live` ×2 — 2+2 passed (~79 с); флейк `children_exit_hook` зелёный 2/2;
  10/10 ответов `system.shutdown` success за ≤2.0 с, exitcode 0. Инвариант Task 1.1 (сокет backend_ctl жив во время
  `stop_all`) цел; ADR-RTR-013 и отказ в спавне после системного стопа не задеты.

## Находки

1. **[major] Исключение в хуке отменяет финальный слив наблюдаемости и повторную остановку детей**
   (`process_module.py:1185`, `process_manager_process.py:3522–3524`). Хук зовётся без `try`, флаг
   `_children_stopped=True` ставится до работы. Вход: `_process_registry.stop_all` бросает `RuntimeError`, затем
   `pm.stop()` и `pm.shutdown()` (как `finally` раннера). Ветка: `stop(): raised RuntimeError`,
   `store still wired (flush skipped) = True`, `stop_all calls total = 1`. main (тот же скрипт): `store still wired =
   False`, `stop_all calls total = 2`. Правка: обернуть хук в `stop()`; флаг ставить после возврата `stop_all` (или
   сбрасывать при исключении); hazard-тест на этот сценарий.
2. **[minor] ADR утверждает, что порядок записи «reported последним» пинуется тестом** — тест
   `test_reported_written_after_numbers_gates_reading` пишет в `RawArray` напрямую и раннер не зовёт. Правка: в ADR
   «порядок записи тестом не закреплён»; переименовать тест в `test_unreported_slot_reads_as_unknown`.
3. **[minor] Неверное объяснение ветки `elif exit_report is not None`** (`process_runner.py:401–404`, ADR п.2) —
   «SRM-режим без bundle» не бывает: `shared_resources` в SRM-режиме не None (строка 273). Реально ветка — класс не
   загрузился / сборка bundle бросила. Вход: `run_process_function("no.such.module.Klass", …, exit_report=s)` →
   `[1, 0, 0]` → в сводке `reported=True, 0/0`, INFO. Поведение честное, объяснение поправить.

## Заметки (не блокируют)

- Память `RawArray` переиспользуется кучей multiprocessing (`del a; b = RawArray('q',3)` → тот же адрес). «Свежий
  слот» держится подтверждённой смертью старого воплощения до `remove_process`, а не новизной объекта — фраза в ADR.
- `GenericProcessManagerApp.shutdown` (watcher'ы, `SSM.shutdown`) теперь идёт ПОСЛЕ `stop_all` (на main — до): в окне
  `stop_all` watcher жив и может разослать reconfigure умирающим детям. Не воспроизведено.
- Выход через сторож смерти родителя: слот `[0,0,0]` → `reported=false`, но PM уже мёртв — не практично.
- `stop()` не переопределяет никто; `shutdown()` — `GenericProcess`, `GuiProcess`, `GenericProcessManagerApp`, все
  зовут `super()`.
- `RawArray` в kwargs под spawn на macOS работает (`[1, 11, 22]` видно PM).

## Не проверено

Настоящий Qt `GuiProcess` (harness поднимает `HeadlessGuiProcess`, qt-mcp не подключён); Windows/spawn; стоп PM без
системного события; матрица инъекций ведущего не повторялась.
