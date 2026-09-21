# apps/line_sim — симулятор линии как второе приложение

Task 1.1 плана [`plans/line-sim/phase-1-vertical-slice.md`](../../plans/line-sim/phase-1-vertical-slice.md)
(«вертикальный срез»). Автономный процессный дерево на том же фреймворке, что
и `multiprocess_prototype/` — прототип о симе не знает и стыкуется по внешним
протоколам (Modbus TCP для робота). Второй, независимый от прототипа
потребитель `app_module` (форма — `examples/minimal_app`).

## Запуск

```bash
FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 BACKEND_CTL_PORT=8766 \
    MULTIPROCESS_LOG_DIR=/tmp/line_sim_logs python apps/line_sim/run.py
```

> **⚠ `FW_SHM_OWNER_INCARNATION=1` — обязателен на POSIX, и в симе, и в прототипе.**
> Без него все процессы-владельцы кадровых колец создают сегменты с голыми именами
> `/output_frames_0..2` и перехватывают их друг у друга: прототип теряет треть кадров
> и читает чужие сегменты, а `hz` в `system_overview` этого не показывает (замер
> стенда Task 1.3, 2026-09-21: дверь 8091 отдавала кадры формы `(1,1,3)` при hz 24.5).
> Это дефект фреймворка, а не сима; задача записана в `docs/claude/OPEN_QUESTIONS.md`
> («SHM-кольца на POSIX…»). Из рецепта флаг не задаётся — только env при запуске.

Поднимает три процесса: `robot`, держащий `SimRobotServer` (Modbus TCP,
`127.0.0.1:5021`); `camera` с `CameraServicePlugin` (`camera_type: simulator`),
который по `chain_targets` отдаёт кадры процессу `mjpeg`; и `mjpeg` с
`MjpegSinkPlugin`, раздающим последний кадр по HTTP MJPEG на `127.0.0.1:8091`.
Остановка — SIGINT (Ctrl+C) или `backend_ctl` `system_command shutdown`.

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

Два процесса: `camera` (`CameraServicePlugin`, `camera_type: simulator`,
генерирует кадры) → по `chain_targets` через SHM-кольцо → `mjpeg`
(`MjpegSinkPlugin`: кодирует в JPEG, раздаёт последний кадр по
`GET http://127.0.0.1:8091/` как `multipart/x-mixed-replace`). Открыть в браузере/`cv2.VideoCapture`/`ffplay`
— обычный MJPEG-клиент. Подробности механизма стока —
[`Plugins/sim/mjpeg_sink/README.md`](../../Plugins/sim/mjpeg_sink/README.md).

Прототип подключается к этому стоку как к источнику `camera_0` через
`multiprocess_prototype/recipes/letter_robot_sim.yaml` (сим-вариант боевого
`hikvision_letter_robot.yaml`, отличается ровно источником `camera_0`).

## Out of scope (Task 1.2)

Живая скорость энкодера от команды ПЧ (Ф2.1), канал энкодера в line-процесс
(Ф2.2), `data/devices.yaml` в репозитории (runtime-файл), объекты/слои/
фотометрия и ROI внутри сима (Ф3–Ф4).
