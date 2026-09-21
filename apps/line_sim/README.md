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

Поднимает два процесса: `robot`, держащий `SimRobotServer` (Modbus TCP,
`127.0.0.1:5021`), и `camera` — линейную цепочку `CameraServicePlugin`
(`camera_type: simulator`) → `MjpegSinkPlugin`, раздающую последний кадр по
HTTP MJPEG на `127.0.0.1:8091`. Остановка — SIGINT (Ctrl+C) или `backend_ctl`
`system_command shutdown`.

## Порты стенда

Фиксируются планом Ф1 line-sim, чтобы прототип и сим не толкались:

| Порт | Что | Владелец |
|---|---|---|
| `8765` | `backend_ctl` | прототип (эксклюзивен) |
| `8766` | `backend_ctl` | сим (`apps/line_sim`) |
| `5021` | Modbus TCP | сим-робот (`SimRobotHostPlugin`) |
| `8091` | MJPEG | сим-камера (`MjpegSinkPlugin`, процесс `camera`, Task 1.2) |

## Как направить прототип на сим

Прототип не знает про сим и подключается к нему как к обычному железу — через
Modbus TCP. Адрес сим-робота (`127.0.0.1:5021`, `unit_id: 2`) записан в секции
`devices:` сим-рецепта `multiprocess_prototype/recipes/letter_robot_sim.yaml`.
Править руками `data/devices.yaml` бесполезно: при активации рецепт делает upsert
устройства (`DeviceManager.upsert`) и перезаписывает `transport` в этом файле.

`vfd_belt` отдельной записи не требует — прототип читает частотник как мост
через самого робота (`Services/device_hub/drivers/robot_driver.py`), тот же
адрес.

## Команды

`sim_robot.status` (процесс `robot`) → `{running, host, port, unit_id,
writes_seen, state}`. Подробности механизма — [`Plugins/sim/robot_host/README.md`](../../Plugins/sim/robot_host/README.md).

## Дверь кадров (Task 1.2)

Процесс `camera` — линейная внутрипроцессная цепочка: `CameraServicePlugin`
(`camera_type: simulator`, генерирует кадры) → `MjpegSinkPlugin` (кодирует в
JPEG, раздаёт последний кадр по `GET http://127.0.0.1:8091/` как
`multipart/x-mixed-replace`). Открыть в браузере/`cv2.VideoCapture`/`ffplay`
— обычный MJPEG-клиент. Подробности механизма стока —
[`Plugins/sim/mjpeg_sink/README.md`](../../Plugins/sim/mjpeg_sink/README.md).

Прототип подключается к этому стоку как к источнику `camera_0` через
`multiprocess_prototype/recipes/letter_robot_sim.yaml` (сим-вариант боевого
`hikvision_letter_robot.yaml`, отличается ровно источником `camera_0`).

## Out of scope (Task 1.2)

Живая скорость энкодера от команды ПЧ (Ф2.1), канал энкодера в line-процесс
(Ф2.2), `data/devices.yaml` в репозитории (runtime-файл), объекты/слои/
фотометрия и ROI внутри сима (Ф3–Ф4).
