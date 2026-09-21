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

## Долг / открытые вопросы

- Пробный bind перед стартом сервера снижает, но не устраняет гонку TOCTOU
  между закрытием пробного сокета и реальным биндом `SimRobotServer` — для
  одиночного процесса на выделенном порту (5021) риск принят, сильнее не
  делали (правка `Services/robot_comm` вне области задачи).
- Нет собственного теста на межпроцессный `record_metric` под реальной
  нагрузкой pymodbus-потока — только на синтетический вызов `_on_write`
  напрямую (реальный сетевой клиент гоняется приёмочным тестом Ф1, не здесь).
