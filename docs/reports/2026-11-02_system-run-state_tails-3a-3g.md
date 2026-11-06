# system-run-state — хвосты стадии 0 (3а–3г), 2026-11-02

**Суть:** четыре вопроса к коду main 886c9cb7a до брифов стадии 1; чтение haiku (Explore), прогноз лида записан до запуска. Сессия inspector-bottles-ec.
**Итог:**

| Хвост | Ожидалось | Получено | Где | Итог |
|---|---|---|---|---|
| 3а `word_layout` как источник «нет диска» | `pred is None` смешивает причины; `readiness()` и поля нет | смешивает (нет списка / нет label / below_threshold / confidence < min); `readiness`, `no_disk` — 0 совпадений | `plugin.py:416-437,501-520` | не годится «как есть» → В10 (блокирует только Task 2.2 п.6) |
| 3б GUI ведёт `ProcessHeartbeat` | да | да по коду (`GuiProcess(ProcessModule)`); runtime-следа нет | `frontend/process.py:27,305-311`, `process_module.py:1370-1373` | код совпал, runtime не подтверждён → стенд `backend_ctl` до брифа 1.3 |
| 3в поток `_on_heartbeat_received`, поля | поток PM, поля целы | поток `message_processor`; dict целиком; `readiness` в `heartbeat_msg` пока нет | `system_threads.py:39,50`, `dispatcher.py:455`, `process_heartbeat.py:362-377` | совпало; сериализацию через IPC-очередь не читали → тест на настоящей очереди (1.2) |
| 3г `restart_process` = тот же spawn | да | да: общий `ProcessRegistry.create_and_register`; `run_event` системный; per-process `stop_event`/`ready_event` создаются заново | `process_manager_process.py:3804,3946`, `process_registry.py:342-343,367-372,411` | совпало для `run_event`; RED на настоящем spawn (1.8 п.5) остаётся |

**Проверка:** `test_close_path_hypotheses.py` 2 passed (через `machine_gate.sh light`). Ветка с планом влита `7a65d9adf`.
**Проблемы → решение:** 3а — не подтвердилось полностью: В10 владельцу (рекомендация лида — разделить причины в `_top_pred`).
**Агенты:** haiku Explore (хвосты 3а–3г), без коммитов.
**Открыто:** В10; runtime-heartbeat GUI; частота вызова `process()` в `word_layout` не измерена; qex устарел (`last_indexed` 2026-10-18), поиск грепом по `*.py`; номера строк сдвинутся после слияний Ф и Д.
**Дальше:** замеры gui-graceful-close 0.1 в окне стенда; стадия 1 после влития Ф, Д, C-55b, gui-graceful-close 1.4.
**Подробно:** `plans/2026-10-27_system-run-state/plan.md` (В10), `tasks/1.2.md`, `1.3.md`, `1.8.md`, `2.2.md`.
