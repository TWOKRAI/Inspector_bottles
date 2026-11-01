# ОТЧЁТ: console-detach — тесты больше не мигают консольными окнами

**Суть:** при полном прогоне тестов на Windows ~50 раз открывались и закрывались консольные окна и мешали работать.
**Причина:** `WindowsConsole.create()` ставил флаг «консоль выделена» даже когда `AllocConsole` отказал (у процесса уже есть консоль без окна — обычное дело под Claude Code). `close()` затем звал `FreeConsole()` и отсоединял pytest от консоли; каждый следующий дочерний процесс (spawn и subprocess) получал своё окно. Заражал сам `test_platforms.py`.
**Итог:** флаг ставится по результату `AllocConsole` (`windows.py`, одна строка). Плагин «тихих тестов» (`CREATE_NO_WINDOW`) отброшен: лечил следствие.
**Проверка:** окон от запуска полного набора за 12 мин (до 40 %, `process_manager_module`): было 45 (23 spawn + 22 subprocess), стало 0. `console_module/tests`: 109 passed (105 + 4 новых); инъекция (вернуть безусловное True): 2 красных (A1 и B), мутанты флага — по 2 красных. `GetConsoleProcessList` pytest на `test_platforms.py`: дефект 5 → 0, исправление 5 → 5.
**Агенты:** developer · sonnet (2 захода) · ~220k; tester (слепой) · sonnet · ~70k; reviewer · sonnet · ~118k — APPROVED. Лид ~UI-оценка не снималась.
**Открыто:** остальные 60 % полного набора под наблюдателем окон не прогонялись; `process_module` с `ConsoleManager` ревьюер не гонял (правка — одна строка в ветке отказа); God Mode (`interactive=True`) не запускался.
**Подробно:** `memory/feedback_a_failed_alloc_console_must_not_arm_free_console.md`; `console_module/tests/test_windows_console_detach_acceptance.py`.
