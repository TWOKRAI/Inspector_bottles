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
| Ревью Task 2.3a, итерация 1 | закрыто: сторож jog под ОДНИМ `self._lock` на весь путь (была гонка, воспроизведена стохастически 3/20000 и детерминированно), боевой dead-man через реальный `_publish_loop` (не только опортунистический `belt.status`), сторож зовётся и на паузе, строгие типы `reverse`/`direction`, `_jog_regs` считается из аргументов (не читается обратно из mailbox) |
| Журнал заданий `sim_robot.journal`/`sim_robot.journal_reset` (Task 5.1) | есть: `SimJournal` заводится в `_start_server` ДО сервера, `_on_write` форвардит КАЖДЫЙ доступ (чтения тоже), уровни `jobs_seen`/`dups_seen`/`dups_same_capture`/`dups_tracked`/`repeats_frozen_xy`/`jobs_done` на такте паблишера, `sim_robot.status.journal` — снимок счётчиков; 4/4 REDS `tests/test_journal_commands.py` зелёные |

Причины повтора (`dups_same_capture`/`dups_tracked`/`repeats_frozen_xy`) — счётная логика в `Services/robot_comm/server/sim_journal.py` (см. его README), не здесь; 4/4 REDS `Services/robot_comm/tests/test_sim_journal_causes.py` зелёные.

## Долг / открытые вопросы

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
