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

---

# Итерация 2 — APPROVE_WITH_NOTES (HEAD 8604e916, фикс 11c2e1cd)

Записано ведущим по отчёту ревьюера.

**Находки it.1:** (1) major закрыта — `probe_raise.py` на HEAD: `store still wired = False`, `stop_all calls total = 3`,
`_children_stopped = False` (a19dc68d: `True / 1`; main: `False / 2`). (2) закрыта — тест переименован в
`test_unreported_slot_reads_as_unknown`, ADR «порядок записи не закреплён». (3) закрыта — комментарий раннера и ADR
описывают ветку верно.

**Прогоны:** `test_system_shutdown_live.py --backend-live` 2 passed / 78.88 с (флейк зелёный);
`test_stop_summary_live.py --backend-live` 3 passed; hazard 7 passed; ruff чисто.

**Новая находка (minor, текст, обязательна до merge):** ADR и комментарий `process_manager_process.py:3530-3533`
утверждали «ровно один раз, пока store-tap жив — включая упавшую первую попытку». Вход: `stop_all` бросает на 1-м
вызове, проходит на 2-м (`probe_it2.py once`) → `stop_all calls=2`, `publish calls=1`, `store_alive_at_publish=[False]`:
повтор идёт из `shutdown()` в конце `stop()` после `_flush_observability()`, сводка в стор не попадает; `finally`
раннера — третий вызов, не второй. **Исправлено ведущим** (текст ADR и комментария, кода нет).

**Заметки:** постоянный сбой `stop_all` — 3 попытки против 2 на main (+1 `shutdown_timeout` в худшем случае);
бросающий `_process_monitor.stop()` → `stop_all calls=0` и на ветке, и на main (не новый дефект, follow-up); двойной
публикации нет; частично сконструированный PM — как на base; разовый сбой `stop()` теперь возвращается штатно (на main
бросал, раннер писал «Process failed») — улучшение; в коммите «7→8 passed» вместо фактических 6→7 — косметика.

**Не проверено:** матрица инъекций ведущего (I8–I11); доезд сводки на пути повтора до файлового лога PM; порядок
«подтверждённая смерть → `remove_process`» — чтением; Qt `GuiProcess`, Windows/spawn.
