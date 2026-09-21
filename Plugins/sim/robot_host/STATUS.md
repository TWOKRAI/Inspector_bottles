# Plugins/sim/robot_host — STATUS

**Состояние: сделано (Task 1.1 плана line-sim, вертикальный срез).**

**Обновлено:** 2026-09-20 — Task 1.1, ветка `feat/line-sim`.

| Что | Состояние |
|---|---|
| `plugin.py` — `SimRobotHostPlugin` | есть: `configure`/`start`/`shutdown`, пробный bind порта до `pymodbus` (с `SO_REUSEADDR` на POSIX — TIME_WAIT не блокирует рестарт), `_on_write` под локом, `sim_robot.status` |
| Деградация без `pymodbus` | есть: `ModbusNotAvailableError` → `report_error`, `state="error"`, процесс живёт |
| Занятый порт | есть: свой пробный сокет, синхронно, до обращения к `SimRobotServer` |
| Метрика `sim_robot.writes` | есть: дельта из `cmd_status`/`shutdown`, не с потока `pymodbus` |
| Паблишер мира (Task 2.2) | есть: воркер `sim_robot_world_publisher`, `sim.belt.encoder` каждые `publish_ms`, уровни `encoder`/`belt_mm_s`/`writes_seen` |
| Тесты | `tests/test_hazards.py` — 4 авторских (a-d); `tests/test_acceptance_time_wait.py` — 4 независимого tester (TIME_WAIT / занятый порт, Task 1.3); приёмочные независимого тестера — `apps/line_sim/tests/test_f1_task11_acceptance.py`, `test_f2_task22_live.py` (вне этого пакета) |
| Команды ленты `belt.*` (Task 2.3a) | есть: `run`/`stop`/`jog`(dead-man `jog_timeout_ms`)/`calibrate`/`status`, mailbox через `RobotSimCore.command_vfd`; 9/10 REDS `tests/test_belt_commands.py` зелёные — 1 открытый вопрос (см. «Долг» ниже); авторские hazard-тесты замка/порядка — `Services/robot_comm/tests/test_belt_drive.py` |

## Долг / открытые вопросы

- Пробный bind перед стартом сервера снижает, но не устраняет гонку TOCTOU
  между закрытием пробного сокета и реальным биндом `SimRobotServer` — для
  одиночного процесса на выделенном порту (5021) риск принят, сильнее не
  делали (правка `Services/robot_comm` вне области задачи).
- Нет собственного теста на межпроцессный `record_metric` под реальной
  нагрузкой pymodbus-потока — только на синтетический вызов `_on_write`
  напрямую (реальный сетевой клиент гоняется приёмочным тестом Ф1, не здесь).
- **REDS `test_jog_without_refresh_stops_in_window` (RED 8, независимый
  tester), первый assert:** `mm_s < 0` требуется СРАЗУ после `belt.jog`, без
  ожидания тика — не выполняется (5/5 детерминированных повторов на этой
  машине, `mm_s=101.1311` — старое "сырое" значение). `command_vfd` только
  пишет mailbox (DESIGN и REDS 5 требуют этого — FLAG остаётся 1 до ЯВНОГО
  `core.tick()`), применение — на следующем тике `SimRobotServer._ticker`
  (`TICK_INTERVAL_S`=0.01с реального времени); две последовательные
  in-process команды в тесте выполняются намного быстрее 10 мс, поэтому окно
  систематически не успевает закрыться. Вторая половина того же теста (окно
  остановки 0.5-1.0с и подкачка ≥1.5с) — зелёная. Файл теста не трогали
  (тестерский, вне FILES этой задачи) — вынесено в отчёт разработчика для
  ведущего/ревьюера, не исправлено самостоятельно.
