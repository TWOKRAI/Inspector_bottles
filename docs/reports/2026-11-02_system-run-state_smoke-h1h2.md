# Смоук пульта (ЗАПУСТИТЬ / ОСТАНОВИТЬ / закрытие) и замеры H1/H2 gui-graceful-close 0.1

**Дата:** 2026-11-02. **Полоса:** Оператор, сессия inspector-bottles-40. **База:** `main` `886c9cb7a`.
**Спецификация замеров:** `plans/2026-10-20_gui-graceful-close/tasks/0.1.md` (H1, H2, базовая линия).

## Предсказания лида (записаны ДО прогона, 2026-11-02)

| # | Что | Ожидается |
|---|---|---|
| H1a | `QMainWindow` с `closeEvent` → `ignore()`, `QApplication.quit()` (PySide6 6.10.x) | `closeEvent` вызван ≥ 1 раз; `app.exec()` не вернулся за 2,0 с |
| H1b | настоящий `MainWindow`, dirty `TopologySession`, `app.quit()` | счётчик `confirm_unsaved_changes` ≥ 1 |
| H2 | живой GUI-стенд, `system.shutdown` через `backend_ctl`, 5 прогонов | 5 из 5: строка `Process 'gui' did not stop in` есть; команда → выход PM 5–8 с; exitcode `gui` ≠ 0 (terminate) |
| БЛ | крестик через qt-mcp, 5 прогонов | 5 из 5: строка `gui` «взведён общий system_stop_event» раньше выхода любого ребёнка в журнале PM |
| S1 | `system.run.start` к PM через `backend_ctl` | отказ: нет обработчика команды (0 из 1 успешных) |
| S2 | `system.run.stop` | то же |
| S3 | `system.run.status` | то же |
| S4 | кадры источника без START | счётчик кадров источника > 0 в первые 15 с после готовности системы (рецепт сразу активен) |
| S5 | кнопки ЗАПУСТИТЬ / ОСТАНОВИТЬ / Квитировать в пульте (`control_panel`) | 0 таких элементов |
| S6 | `system.shutdown` (graceful) через `backend_ctl`, headless | PM вышел ≤ 15 с; 0 живых PID детей после выхода PM |

Несовпадение предсказания с замером — находка; разбор — ниже, после таблицы замеров.

## Замеры

Исполнитель: measurement executor, полоса «Оператор» (inspector-bottles-40), окно стенда 15:36–15:58 2026-11-02, PySide6 6.10.3, Qt 6.10.3. Логи прогонов — `logs_live/2026-11-02_op_*` и `logs_live/2026-11-02_op_smoke_2` в worktree (не в git).

### Таблица «ожидалось / получено»

| # | ожидалось | получено | совпало (да/нет) |
|---|---|---|---|
| H1a | closeEvent ≥ 1; `exec()` не вернулся за 2,0 с | closeEvent: 1; `exec()` не вернулся, сработал дедлайн 2,000 с | да |
| H1b | `confirm_unsaved_changes` ≥ 1 после `app.quit()` | `confirm_unsaved_changes`: 1; `exec()` не вернулся, дедлайн 2,000 с | да |
| H2a | 5 из 5: строка `did not stop in` есть | 5 из 5 (5,2 / 5,5 / 5,4 / 5,2 / 5,4 с) | да |
| H2b | команда → выход PM 5–8 с | 5,344 / 5,641 / 5,640 / 5,438 / 5,641 с | да |
| H2c | exitcode `gui` ≠ 0 (terminate) | не измерено: PM не пишет код выхода, только `not reported/lost: ['gui']` | не измерено |
| БЛ | 5 из 5: строка gui «взведён общий system_stop_event» раньше выхода любого ребёнка в журнале PM | 5 из 5: строка gui раньше строки PM «Stop signal received» (разница 13 / 84 / 33 / 93 / 72 мс). Выход детей в журнале PM не пишется, поэтому сравнение «раньше выхода ребёнка» не выполнено | не измерено (относительно PM: 5 из 5 да) |
| S1 | `system.run.start`: отказ «нет обработчика» | `{"success": false, "result": {"status": "error", "reason": "No handler for key 'system.run.start'"}}` | да |
| S2 | `system.run.stop`: то же | `No handler for key 'system.run.stop'` | да |
| S3 | `system.run.status`: то же | `No handler for key 'system.run.status'` | да |
| S4 | счётчик кадров источника > 0 в первые 15 с без START | `frames` = 0 при T0 и при T+15 с (`device_state: not_found`, IP 192.168.1.10). Worker `source_producer_code_reader_sdk` работает: cycles 929 → 1463 за ~26 с, 20 Hz | нет |
| S5 | 0 элементов ЗАПУСТИТЬ / ОСТАНОВИТЬ / Квитировать | 0 в активном рецепте (`control_panel` нет). В `recipes/*.yaml` меток 0 вхождений; `control_panel` есть в phone_sketch (4), pult_demo (5), webcam_sketch (4), но с другими метками (Старт, Свет, Скорость, Слово…) | да |
| S6 | PM вышел ≤ 15 с; 0 живых PID детей | `accepted: true`, `elapsed_s` 0,61, `pm_gone: true`; 7 PID (PM + 6 детей): tasklist — «нет запущенных задач» для всех 7 | да |

### Сырые числа

**H1** (вывод pytest, `-s`):
- H1a: `close_calls=1 deadline_fired=True exec_seconds=2.000`
- H1b: `confirm_calls=1 deadline_fired=True exec_seconds=2.000`
- pytest `test_close_path_hypotheses.py`: первый прогон 2 failed (assert на плейсхолдерах; значения взяты из вывода), второй прогон 2 passed, exit 0.

**H2** (5 прогонов, `frontend/run.py`, `system_shutdown` graceful):

| прогон | elapsed_s (команда → PM закрыл сокет) | строка PM | stop summary |
|---|---|---|---|
| 1 | 5,344 | `Process 'gui' did not stop in 5.2s, terminating...` | `not reported/lost: ['gui']`, children=6 |
| 2 | 5,641 | `... did not stop in 5.5s, terminating...` | то же |
| 3 | 5,640 | `... did not stop in 5.4s, terminating...` | то же |
| 4 | 5,438 | `... did not stop in 5.2s, terminating...` | то же |
| 5 | 5,641 | `... did not stop in 5.4s, terminating...` | то же |

**БЛ** (закрытие через `qt_invoke_slot(MainWindow, close)`; времена из `ProcessManager/messages.log` и `gui/*.log`):

| прогон | gui: `взведён общий system_stop_event` | PM: `Stop signal received` | PM: `shut down successfully` |
|---|---|---|---|
| 1 | 15:48:19,460 | 15:48:19,473 | 15:48:20,660 |
| 2 | 15:50:34,925 | 15:50:35,009 | 15:50:36,203 |
| 3 | 15:52:38,640 | 15:52:38,673 | 15:52:39,706 |
| 4 | 15:55:08,665 | 15:55:08,758 | 15:55:10,613 |
| 5 | 15:58:02,761 | 15:58:02,833 | 15:58:04,411 |

Для прогона 1 последние строки логов детей (`devices`, `draw_1`, `draw_2`, `reader_1`, `reader_2`, `gui`) — 15:48:19,484 … 15:48:19,589, то есть после метки gui. Для прогона 2 последние строки детей — 15:49:23 … 15:49:30, то есть за ~70 с до закрытия; эта метка выхода детей ненадёжна (см. ниже).

### Что осталось открытым / ненадёжно

1. **БЛ: выход детей не измерен.** В журнале PM нет строк выхода детей. Прокси «последняя строка лога ребёнка» непригоден: в прогоне 2 строки детей старше закрытия на ~70 с. Нужна явная метка выхода детей или pid-проверка по времени.
2. **H2c: exitcode `gui` не получен.** PM пишет только `not reported/lost: ['gui']`, код выхода не логируется. Вывод «terminate» опирается на строку `did not stop in … terminating`, а не на код.
3. **H2 запущен через `system_shutdown`** (backend_ctl), а не через `system_command({"cmd": "system.shutdown"})`. Это та же команда плюс ожидание закрытия сокета. Эквивалентность не проверялась.
4. **Живость PID детей в H2 и БЛ не проверена.** Выборка процессов через PowerShell отклонена классификатором auto-mode; PID детей для H2/БЛ не снимались. Для H2 есть `pm_gone: true`, для БЛ — строки `shut down successfully`. «0 живых PID» подтверждено только для S6 (tasklist по 7 PID).
5. **qt-mcp:** probe на localhost:9142 не отвечал 20–60 с после старта (5 вызовов «Connection closed/lost», потом ответ). Ждал по времени, без повторов в цикле. «Крестик» не кликался: закрытие — `close()` главного окна (`w1`), что вызывает тот же `closeEvent`, как в ТЗ.
6. **H1 литералы:** первый прогон красный из-за плейсхолдеров (значения записаны из вывода), второй зелёный. Тест фиксирует поведение Qt 6.10.3 на этой машине при QT_QPA_PLATFORM=offscreen.
7. **S4:** источник не стартует с device not found (192.168.1.10/.11 недоступны). Нулевой счётчик кадров здесь — условие стенда, а не доказательство «источник не работает без START». Циклы worker'а растут, это проверено.
8. **S5:** проверено по `recipes/*.yaml`, не по коду `Services/`. Активный рецепт определён по топологии (два reader с IP .10/.11 → `qr_reader_sdk_dual_*`), а не по логу PM: в логе имени рецепта нет. У `qr_reader_sdk_dual_*` `control_panel` отсутствует.
9. **Ход работ:** первый фоновый запуск smoke (через `&`) не поднял стенд (лог-каталога не появилось). Первый foreground-прогон (timeout 90 с) PID не снимал. Запуск `smoke_2` — первый успешный. Команда с `rm -rf` отклонена классификатором, повторена без неё. PowerShell-список процессов отклонён тоже.
10. **Память:** RAM free 1250–2085 МБ во время прогонов.
11. **Файлы:** создан только `multiprocess_prototype/frontend/tests/test_close_path_hypotheses.py`. `backend_ctl/probes/probe_gui_close_order_live.py` НЕ создан: измерения шли через MCP-инструменты backend_ctl и qt-mcp и grep по логам. Коммитов и push нет; логи и тест — untracked в worktree.
