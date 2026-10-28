# T5.3 круг 2 — стенд через PM / backend_ctl (2026-10-19 11:49–11:55)

HEAD `2cc25c82b` (код = `1fc2a37ab`). Процесс `devices` поднят `BackendHarness(with_base=True)`, роботы — симуляторы v2 на свободных портах, движение — задание CVT (`robot_enqueue_job`). Остановка — `ProcessManager process.stop {"process_name": "devices"}`. Скрипт — `stand_t53r2.py` (README рядом). Окно и `stand.lock` — inspector-bottles-59.

Обозначения: «плагин» — время от `process.stop` до строки `DeviceHubPlugin: shutdown` в логе `devices` (момент обнаружения скриптом); «PM» — время до ответа PM на `process.stop` (= процесс остановлен или убит); «записи» — записи STOP_REQ на стороне робота в окне [t0, t0+6 с]; «журнал» — строки STOP_REQ в `devices/robot_exchange.log` (T5.6).

| сценарий | повтор | плагин, с | PM, с | записи r1 / r2 | журнал r1 / r2 | статус `devices` |
|---|---|---|---|---|---|---|
| s1: 1 робот, эхо есть | 1 | 0.17 | 0.41 | 1 / — | 1 / — | stopped |
| s2: 1 робот, эха нет | 1 | 0.70 | 0.88 | 1 / — | 1 / — | stopped |
| s2 | 2 | 0.66 | 0.81 | 1 / — | 1 / — | stopped |
| s2 | 3 | 0.77 | 0.95 | 1 / — | 1 / — | stopped |
| s3: 2 робота, эха нет | 1 | 0.67 | 5.05 | 1 / 1 | 1 / 1 | crashed (L-9) |
| s3 | 2 | 0.72 | 0.97 | 1 / 1 | 1 / 1 | stopped |
| s3 | 3 | 0.61 | 5.05 | 1 / 1 | 1 / 1 | crashed (L-9) |
| s4: 2 робота, ответ r1 на запись задержан 3 с | 1 | 2.19 | 5.06 | 2 / 1 | 2 / 1 | crashed (L-9) |
| s4 + r1 без эха | 1 | 2.11 | 5.08 | 2 / 1 | 2 / 1 | crashed (L-9) |

- s2: плагин min / медиана / max = 0.66 / 0.70 / 0.77 с. s3: 0.61 / 0.67 / 0.72 с. Разброс первых записей r1 и r2 в s3: 0.016 / 0.0 / 0.0 с.
- s4: вторая запись r1 через 1.0 с после первой — повтор после таймаута записи (исключение ADR-DH-009).
- s5: `devices` убит (`BackendHarness.kill_child`, PID, `FW_AUTORESTART=0`) при движении: симулятор `E_WDG_TIMEOUT` через 3.016 с после kill и 3.0 с после последней смены HB_PC; `P_WDG_TIMEOUT_MS = 3000`; `TLM_MOVING` в конце 0.
- «crashed»: процесс `devices` не вышел после `Process 'devices' shut down successfully`, PM убил его по своему сроку 5 с. Причина — фреймворк, дефект L-9 (`docs/reviews/2026-10-19_L-9_pm-stop-exit-hang.md` в main; копия разбора — `inv_exit_hang.md`). Код T5.3 на стеке зависания отсутствует.

Не мерилось: стоп в jog (нет команды `robot_jog_hold` в backend_ctl до T5.3d), `system.shutdown`, авторестарт PM. Выборка: s2 и s3 по 3 повтора, s4 по 1. Времена — моменты обнаружения строки скриптом (опрос 25 мс).
