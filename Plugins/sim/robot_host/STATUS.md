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
| Тесты | `tests/test_hazards.py` — 10 авторских (a-d, e, плюс 6 ревью Task 2.3a — см. ниже); `tests/test_acceptance_time_wait.py` — 4 независимого tester (TIME_WAIT / занятый порт, Task 1.3); приёмочные независимого тестера — `apps/line_sim/tests/test_f1_task11_acceptance.py`, `test_f2_task22_live.py` (вне этого пакета) |
| Команды ленты `belt.*` (Task 2.3a) | есть: `run`/`stop`/`jog`(dead-man `jog_timeout_ms`)/`calibrate`/`status`, mailbox через `RobotSimCore.command_vfd`; 7/7 REDS `tests/test_belt_commands.py` зелёные (RED 8 открытый вопрос закрыт коммитом `7acf6d9b` — интерпретация «трогается сразу» = за тик, не синхронно) |
| Ревью Task 2.3a, итерация 1 | закрыто: сторож jog под ОДНИМ `self._lock` на весь путь (была гонка, воспроизведена стохастически 3/20000 и детерминированно), боевой dead-man через реальный `_publish_loop` (не только опортунистический `belt.status`), сторож зовётся и на паузе, строгие типы `reverse`/`direction`, `_jog_regs` считается из аргументов (не читается обратно из mailbox) |

## Долг / открытые вопросы

- Пробный bind перед стартом сервера снижает, но не устраняет гонку TOCTOU
  между закрытием пробного сокета и реальным биндом `SimRobotServer` — для
  одиночного процесса на выделенном порту (5021) риск принят, сильнее не
  делали (правка `Services/robot_comm` вне области задачи).
- Нет собственного теста на межпроцессный `record_metric` под реальной
  нагрузкой pymodbus-потока — только на синтетический вызов `_on_write`
  напрямую (реальный сетевой клиент гоняется приёмочным тестом Ф1, не здесь).
- **`cmd_belt_jog` считает `_jog_regs` из аргументов, а не читает обратно
  mailbox (ревью, п.2)** — нет отдельного break-injection теста на ЭТОТ
  конкретный сценарий (Modbus-запись другого мастера в окне между записью и
  обратным чтением); полный прогон `Services/robot_comm/tests` +
  `Plugins/sim/robot_host/tests` остаётся зелёным и при откате этой правки
  — гэп зафиксирован разработчиком для ведущего/ревьюера, отдельно не
  закрывался.
