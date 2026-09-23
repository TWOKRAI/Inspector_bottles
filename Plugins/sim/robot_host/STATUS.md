# Plugins/sim/robot_host — STATUS

**Состояние: сделано, ревью Task 2.3a итерация 1 закрыта.**

**Обновлено:** 2026-09-22 — ревью Task 2.3a (замок сторожа jog, боевой
dead-man путь, строгие типы аргументов), ветка `feat/line-sim-2.3a-commands`.

| Что | Состояние |
|---|---|
| `plugin.py` — `SimRobotHostPlugin` | есть: `configure`/`start`/`shutdown`, пробный bind порта до `pymodbus` (с `SO_REUSEADDR` на POSIX — TIME_WAIT не блокирует рестарт), `_on_write` под локом, `sim_robot.status` |
| Деградация без `pymodbus` | есть: `ModbusNotAvailableError` → `report_error`, `state="error"`, процесс живёт |
| Занятый порт | есть: свой пробный сокет, синхронно, до обращения к `SimRobotServer` |
| Метрика `sim_robot.writes` | есть: дельта из `cmd_status`/`shutdown`, не с потока `pymodbus` |
| Паблишер мира (Task 2.2) | есть: воркер `sim_robot_world_publisher`, `sim.belt.encoder` каждые `publish_ms`, уровни `encoder`/`belt_mm_s`/`writes_seen` |
| Тесты | `tests/test_hazards.py` — 11 авторских (a-d, e, 6 ревью Task 2.3a, 1 страж п.2 от ведущего); `tests/test_acceptance_time_wait.py` — 4 независимого tester (TIME_WAIT / занятый порт, Task 1.3); `tests/test_journal_commands.py` — 4 независимого tester (Task 5.1, RED-приёмка команд журнала); `tests/test_journal_hazards.py` — 2 авторских (Task 5.1: `drain` такта публикации против `on_write` приёмного потока, `journal_reset` посреди потока заданий); приёмочные независимого тестера — `apps/line_sim/tests/test_f1_task11_acceptance.py`, `test_f2_task22_live.py` (вне этого пакета) |
| Команды ленты `belt.*` (Task 2.3a) | есть: `run`/`stop`/`jog`(dead-man `jog_timeout_ms`)/`calibrate`/`status`, mailbox через `RobotSimCore.command_vfd`; 7/7 REDS `tests/test_belt_commands.py` зелёные (RED 8 открытый вопрос закрыт коммитом `7acf6d9b` — интерпретация «трогается сразу» = за тик, не синхронно) |
| Событие «задание выполнено» (Task 3.5b) | есть: `RobotSimCore(on_job_done=...)` → `scene.job_done` в `scene_process` (fire-and-forget, сбой → `report_error` с throttle 30 с, не бросает); `tests/test_job_done_forward.py` (tester) — 5/5 |
| Ручка `job_ms` (Task 5.3b) | есть: конфиг `job_ms` → `job_ticks` ядра (`max(1, round(job_ms/(TICK_INTERVAL_S*1000)))`), плохой `job_ms` → `state="error"` через `_fail`; `tests/test_acceptance_5_3b_job_ms.py` (tester) — 5/5, `tests/test_hazards.py::test_job_ms_rounding_to_zero_still_yields_minimum_one_tick` (автор) |
| Ревью Task 2.3a, итерация 1 | закрыто: сторож jog под ОДНИМ `self._lock` на весь путь (была гонка, воспроизведена стохастически 3/20000 и детерминированно), боевой dead-man через реальный `_publish_loop` (не только опортунистический `belt.status`), сторож зовётся и на паузе, строгие типы `reverse`/`direction`, `_jog_regs` считается из аргументов (не читается обратно из mailbox) |
| Журнал заданий `sim_robot.journal`/`sim_robot.journal_reset` (Task 5.1) | есть: `SimJournal` заводится в `_start_server` ДО сервера, `_on_write` форвардит КАЖДЫЙ доступ (чтения тоже), уровни `jobs_seen`/`dups_seen`/`dups_same_capture`/`dups_tracked`/`jobs_done` на такте паблишера, `sim_robot.status.journal` — снимок счётчиков; 4/4 REDS `tests/test_journal_commands.py` зелёные |
| Причина «те же X/Y» ушла из журнала (Task 5.1b) | `repeats_frozen_xy` не заводится и не публикуется robot_host — переехала в `TruthLedger.false_alarm_frozen_xy` на стороне сцены; 2/2 REDS `tests/test_acceptance_5_1b.py` зелёные |

Причины повтора (`dups_same_capture`/`dups_tracked`) — счётная логика в `Services/robot_comm/server/sim_journal.py` (см. его README), не здесь; 4/4 REDS `Services/robot_comm/tests/test_sim_journal_causes.py` зелёные.

| Ручки неисправностей `fault.*` (Task 5.4) | есть: `fault.drop`/`fault.delay_ms`/`fault.vfd_code`/`fault.clear`, `sim_robot.status.faults`; `SimRobotServer.stop_listener()`/`start_listener()` разводят слушателя и тикер (drop — обрыв связи, не перезагрузка); 8/9 REDS `tests/test_acceptance_5_4_faults.py` зелёные (1 открытый вопрос — см. ниже); 4/4 авторских `tests/test_faults_hazards.py` (shutdown посреди drop, drop сам уходит из faults, два drop подряд, shutdown сразу за clear) |

## Долг / открытые вопросы

- `tests/test_acceptance_5_4_faults.py::test_bad_args_and_no_server` красный: вторая половина
  теста конструирует плагин с `auto_start=False`, потом зовёт `plugin.start(ctx)` и ждёт
  `plugin._state == "running"` — но `start()` (код вне области Task 5.4, существовал ДО задачи)
  запускает `_start_server()` ТОЛЬКО если `self._auto_start` истинно (см. `plugin.py`, `start()`).
  С `auto_start=False` сервер НЕ поднимается никаким вызовом `start()` — так же ведут себя
  все остальные тесты пакета с `auto_start=False` (`test_belt_commands.py:258-264`,
  `test_journal_commands.py:190`) — ни один из них не пытается затем поднять сервер через
  `start()`. Не правил тест (запрещено брифом) и не менял поведение `auto_start` (вне
  FILES/DESIGN Task 5.4) — эскалировано лиду.

- Task 3.5b: пересылка события проверена на подменённом `DeviceHubClient` и смоуком с
  реальным `SimRobotServer` + реальным клиентом на мок-роутере; межпроцессная доставка
  до процесса `camera` — живой стенд лида.
- Пробный bind перед стартом сервера снижает, но не устраняет гонку TOCTOU
  между закрытием пробного сокета и реальным биндом `SimRobotServer` — для
  одиночного процесса на выделенном порту (5021) риск принят, сильнее не
  делали (правка `Services/robot_comm` вне области задачи).
- Нет собственного теста на межпроцессный `record_metric` под реальной
  нагрузкой pymodbus-потока — только на синтетический вызов `_on_write`
  напрямую (реальный сетевой клиент гоняется приёмочным тестом Ф1, не здесь).
- Остаточное окно внешнего Modbus-мастера: поток pymodbus пишет mailbox без
  замка плагина; запись, попавшая между чтением mailbox сторожем и его стопом,
  будет перетёрта стопом («побеждает последний записавший»). Не воспроизводилось
  (ревью 2.3a, итерация 2).
