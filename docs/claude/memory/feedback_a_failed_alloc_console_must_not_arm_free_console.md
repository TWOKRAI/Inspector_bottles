---
name: feedback-a-failed-alloc-console-must-not-arm-free-console
description: "Тесты мигают консольными окнами (~45 за прогон): WindowsConsole.create() ставил флаг при отказавшем AllocConsole, close() звал FreeConsole и отсоединял pytest от консоли; каждый следующий ребёнок получал своё окно (console window flash, spawn, subprocess, CREATE_NO_WINDOW, GetConsoleProcessList)"
module: [console_module]
mechanism: [windows-env, break-injection]
metadata:
  node_type: memory
  type: feedback
---

**Ловушка.** Под Claude Code / ConPTY у процесса есть консоль, но без окна: `GetConsoleWindow()==0`.
`WindowsConsole.create()` звал `AllocConsole()`, тот ОТКАЗЫВАЛ (процесс уже присоединён), но флаг
`_allocated_console = True` ставился безусловно. `close()` звал `FreeConsole()` — процесс терял консоль, и каждый
дочерний процесс после этого (`multiprocessing` spawn и `subprocess`) получал собственное видимое окно.
Замер: полный прогон `scripts/run_framework_tests.py` — 45 окон от одного запуска (23 spawn + 22 subprocess),
первое на 9-й минуте; после исправления на том же месте набора — 0.

**Замер (вход → выход).**
- `GetConsoleProcessList` процесса pytest: на дефектном коде `test_platforms.py` один даёт 5 → 0, на исправленном 5 → 5.
- Ребёнок после отсоединения: `child_hwnd=4918172` (своё окно); до — `child_hwnd=0`.
- Из-за этого окна идут пачкой только в ПОЛНОМ прогоне: после заразившего теста. Один модуль `process_manager_module/tests` дал 0 окон в обоих режимах.

**Исправление.** `self._allocated_console = bool(kernel32.AllocConsole())` — флаг только по результату вызова.

**Урок о тесте.** Тест «create()+close() не отсоединяет процесс» в дочернем процессе запускать с
`creationflags=subprocess.CREATE_NO_WINDOW`: без флага ребёнок наследует состояние родителя, и если pytest уже
отсоединён заразившим тестом, ребёнок получает своё окно, `AllocConsole` ему не отказывает, тест вакуумен
(до 1, после 1). Инъекция (вернуть безусловное `True`) в прогоне директории дала 1 красный вместо 2 — так это и
нашли. Ребёнка БЕЗ консоли вообще делают `DETACHED_PROCESS` через `sys._base_executable`, не через venv-лаунчер
`Scripts\python.exe` (лаунчер сам выдаёт своему ребёнку окно).

**Как применять.** Любой код, который зовёт `FreeConsole`/`AttachConsole`, обязан зависеть от результата своего
`AllocConsole`, не от «мы пытались». Мигание окон в тестах на Windows — сначала `GetConsoleProcessList` у pytest
до/после подозреваемого теста, потом уже обёртки запуска (`CREATE_NO_WINDOW` в плагине лишь маскирует часть
следствий). Порядковая зависимость («только в полном прогоне») — признак заражения общего состояния процесса.
