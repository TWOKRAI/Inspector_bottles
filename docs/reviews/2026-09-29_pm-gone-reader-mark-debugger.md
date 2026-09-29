# pm-mark: красный test_mark_only_after_confirmed_death на Windows — отчёт debugger

Ветка `fix/pm-gone-reader-mark` (от main 97bdcf9b). План: `plans/lifecycle-stop-ownership.md`, Task 1.2.

## Воспроизведение

    PYTHONPATH=$PWD .venv/Scripts/python.exe -m pytest -q --tb=short \
      multiprocess_framework/modules/process_manager_module/tests/test_pm_marks_gone_reader_hazards.py::test_mark_only_after_confirmed_death

3/3 красных: `assert watcher.pid_present_at_mark is False` -> наблюдено `True`.

## Причина: сторона (b), проба в тесте

`_MarkWatcher` проверял «pid ещё есть» через `os.kill(pid, 0)` и ловил `ProcessLookupError`. Это POSIX-семантика.
На Windows сигнал 0 равен `CTRL_C_EVENT` и уходит в `GenerateConsoleCtrlEvent`, живость не проверяется.

Замер (Python 3.12.12, Windows 10, spawn-процесс, `Process.terminate()` + `join`):

| состояние pid                                        | `os.kill(pid, 0)`              | код выхода (`GetExitCodeProcess`) |
|------------------------------------------------------|--------------------------------|-----------------------------------|
| живой                                                | успех                          | STILL_ACTIVE                      |
| мёртв, kernel-объект держит `Process` родителя       | успех                          | exited (65536)                    |
| мёртв, после `Process.close()`                       | успех                          | exited (65536)                    |
| давно несуществующий pid (999999)                    | `OSError [WinError 87]`        | OpenProcess не открылся           |

То есть проба отвечает «есть» и по подтверждённо мёртвому процессу, а на исчезнувшем pid бросает не тот тип исключения
(`OSError`, не `ProcessLookupError`) — поток вотчера умер бы с `pid_present_at_mark is None`.

Продукт корректен: `Process.is_alive()` на Windows — это ожидание sentinel-дескриптора с нулевым таймаутом
(эквивалент кода выхода != STILL_ACTIVE); метка в `stop_one` ставится только после `_stop_one`, вернувшего `not alive`.

## Исправление (только тест)

`_pid_present(pid)`: POSIX — прежний `os.kill(pid, 0)`; Windows — `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
`GetExitCodeProcess`, «присутствует» = код выхода STILL_ACTIVE (259). Свойство теста не ослаблено: метка, видимая
при ещё выполняющемся процессе, по-прежнему даёт `True` и валит ассерт.

## Приёмка

- целевой тест: 10/10 зелёных (exit 0 в каждом прогоне);
- `process_manager_module/tests` целиком, дважды: 993 passed, 31 skipped, 0 failed (60 с и 57 с).

## Что не сделано / ненадёжно

- Break-injection (метка до terminate -> тест должен стать красным) не выполнена: sandbox отклонил команду с временной
  правкой продукта. Что тест ловит именно «метка до смерти», не доказано мной — это шаг ведущего.
- Не выяснено, почему kernel-объект убитого процесса остаётся открываемым и после `Process.close()` (вероятно,
  другой держатель дескриптора); на вывод не влияет: код выхода проверяется независимо от этого.
- Проба через `ctypes` проверена только на Windows 10 / Python 3.12; POSIX-ветка не менялась и здесь не запускалась.
