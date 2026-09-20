# apps/line_sim — симулятор линии как второе приложение

Task 1.1 плана [`plans/line-sim/phase-1-vertical-slice.md`](../../plans/line-sim/phase-1-vertical-slice.md)
(«вертикальный срез»). Автономный процессный дерево на том же фреймворке, что
и `multiprocess_prototype/` — прототип о симе не знает и стыкуется по внешним
протоколам (Modbus TCP для робота). Второй, независимый от прототипа
потребитель `app_module` (форма — `examples/minimal_app`).

## Запуск

```bash
BACKEND_CTL=1 BACKEND_CTL_PORT=8766 MULTIPROCESS_LOG_DIR=/tmp/line_sim_logs \
    python apps/line_sim/run.py
```

Поднимает один процесс `robot`, держащий `SimRobotServer` (Modbus TCP,
`127.0.0.1:5021`). Остановка — SIGINT (Ctrl+C) или `backend_ctl`
`system_command shutdown`.

## Порты стенда

Фиксируются планом Ф1 line-sim, чтобы прототип и сим не толкались:

| Порт | Что | Владелец |
|---|---|---|
| `8765` | `backend_ctl` | прототип (эксклюзивен) |
| `8766` | `backend_ctl` | сим (`apps/line_sim`) |
| `5021` | Modbus TCP | сим-робот (`SimRobotHostPlugin`) |
| `8090` | MJPEG | сим-камера (Task 1.2, ещё не реализовано) |

## Как направить прототип на сим

Прототип не знает про сим и подключается к нему как к обычному железу — через
Modbus TCP. В `data/devices.yaml` прототипа (runtime-файл, **не** в репозитории
— заводится оператором на стенде):

```yaml
robot_main:
  host: 127.0.0.1
  port: 5021
```

`vfd_belt` отдельной записи не требует — прототип читает частотник как мост
через самого робота (`Services/device_hub/drivers/robot_driver.py`), тот же
адрес.

## Команды

`sim_robot.status` (процесс `robot`) → `{running, host, port, unit_id,
writes_seen, state}`. Подробности механизма — [`Plugins/sim/robot_host/README.md`](../../Plugins/sim/robot_host/README.md).

## Out of scope (Task 1.1)

Кадры/камера (Task 1.2 — MJPEG-сток на `:8090`), живая скорость энкодера от
команды ПЧ (Ф2.1), канал энкодера в line-процесс (Ф2.2), `data/devices.yaml` в
репозитории (runtime-файл).
