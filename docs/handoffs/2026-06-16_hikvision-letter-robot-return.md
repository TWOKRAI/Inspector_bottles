---
date: 2026-06-16
topic: hikvision_letter_robot — калибровка px→мм + укладка слова + ВОЗВРАТ на ленту
machine: Windows
branch: feat/pult-control-panel
---

## Session goal

Достроить полный цикл рецепта `hikvision_letter_robot`: камера Hikvision → распознавание
буквы+угла → `word_layout` раскладывает слово, робот **берёт диск с ленты и кладёт в слот**;
по сигналу с телефона робот **возвращает ВСЕ выложенные буквы на конвейер** (захват →
+20 Z → +100 X → −20 Z → отпустить, линейно), затем можно вводить новое слово. Плюс
«притулить калибровку камеры» (px→мм) — без неё координаты забора неверны.

## Done

- **Узел `pixel_to_robot`** (новый, `Plugins/processing/pixel_to_robot/`): грузит
  `config/calibration/cam0.yaml` (гомография визарда) → переводит центр сработавшего круга
  (`sidecar.center_px` от `center_crop`) в `pick_xy` (мм робота). 7 тестов.
- **`word_layout`**: принимает `pick_xy`, в job кладёт забор (`pick_*`+`e_capture`) и укладку
  (`place_*`+доворот). `require_pick=True` → без калибровки слот не занимает (прод-safe).
  Сигнал `signal_1` → возврат всех заполненных слотов (`robot_return_jobs`) + сброс. 20 тестов.
- **`robot_io`**: форвардит полную позу укладки (раньше резал до X/Y) + новый путь возврата
  (`robot_return_job`, через служебный ключ `_command` в deque). 13 тестов.
- **RETURN-цепочка**: `RobotClient.do_return` + регистры `0x1510-0x1514` (`registers.py` +
  `delta_universal3.yaml`) + `RobotDriver` op `return_job` (очередь + tick переключает MODE→
  return→cvt) + device_hub команда `robot_return_job` + **sim `RobotSimCore._handle_return`**
  (исполняемая спецификация handshake). `enqueue_job` принимает готовый `e_capture`.
- **Рецепт** `hikvision_letter_robot.yaml`: 10 процессов, блок `devices` (robot+ПЧ), узел
  `calib` между crop и infer, `robot_io`, провод сигнала возврата, ROI калибровки = боевой.
- **ТЗ прошивки** `robot/universal3/RETURN_MODE.md` — карта регистров + последовательность.
- Итог: **200 тестов зелёные**, ruff check+format чисто. Рецепт реально поднимается (10 проц.,
  проверено запуском прототипа владельцем).

## What did NOT work

- **Поллер энкодера в `pixel_to_robot` (continuous `robot_get_telemetry` @20Hz) — ОТКАЧЕН.**
  Идея была снять энкодер рано (до инференса) для точного CVT-трекинга. Но это «частый стук
  по Modbus» (владелец против) + флудил WARNING'ами `robot_get_telemetry failed` когда робот
  не подключён. Решение: энкодер читается ОДИН раз в `enqueue_job` (драйвер), и только при
  `is_connected` → ноль обращений вхолостую. `pixel_to_robot` снова чистый px→мм.
- **Блокирующий IPC-запрос в `process()` — ЗАПРЕЩЁН.** Контракт `DeviceHubClient` (docstring):
  `request()` нельзя из `process()`/приёмного цикла — дедлок. Поэтому «свежий on-demand read на
  триггере» из vision-узла недостижим без поллинга. Отсюда выбор «один read при enqueue».
- **Провод рецепта `target: robot_io.robot_job` (2 сегмента) — упал валидацией Blueprint.**
  Формат `процесс.плагин.порт` (3 сегмента): `robot_io.robot_io.robot_job` (процесс и плагин
  оба `robot_io`). Из-за этого `apply` падал → откат → старый рецепт оставался висеть, что
  ВЫГЛЯДЕЛО как «переключение не останавливает прошлый». Починено. Добавил строгую headless-
  проверку портов (резолв через `inputs/outputs` плагинов) — ловит весь класс.
- **5-сек хан­г при переключении рецептов** («Process X did not stop in 5.0s, terminating»,
  «still alive after join») — это ПРЕД-существующий долг `project_graceful_stop_debt`, НЕ из
  этой фичи. Не трогал.

## Key decisions made

- Калибровку применяем к `sidecar.center_px` (именно сработавший диск), узел ДО инференса —
  не к сырым `detections` (там все круги).
- Захват (`DO(DO_GRIP)`) и вся траектория возврата — ЦЕЛИКОМ в Lua; ПК шлёт только команду+
  координаты (решение владельца). `DO` в `run_job` сейчас закомментирован — раскоммитить.
- RETURN = новый MODE=3 (CVT-забор по энкодеру/DRAW-перо/MANUAL-без-Z не подходят). Зона
  регистров `0x1510` (в пределах `REG_SPACE_SIZE=0x1600`, без правки sim-пространства).
- Рисование — отдельный рецепт; режим DRAW не трогаем (сосуществует в той же прошивке).
- Конвейер — через сервис ПЧ (`vfd_belt`, мост поверх `robot_main`).

## Next step

Прогнать визард `camera_robot_calibration` **с ROI `560,240,800,600`** → получить
`config/calibration/cam0.yaml` (без него `pick_xy` пустой и робот стоит — это первый
блокер укладки; прошивка MODE=3 RETURN по `robot/universal3/RETURN_MODE.md` — следующий шаг).

## ⚠ Перед сменой машины

Вся работа сессии **НЕ закоммичена** (`git status` ниже) — на другой машине `git pull`
ничего не даст, пока не сделать коммит+push. Коммитить сериями по фазам с trailers
`Why:`/`Layer: mixed`/`Refs: plans/...`.

## Files changed

**Новые (этой сессии):**
- `Plugins/processing/pixel_to_robot/` (плагин + registers + config + tests)
- `robot/universal3/RETURN_MODE.md` (ТЗ прошивки)

**Изменены (этой сессии):**
- `Plugins/processing/word_layout/{plugin,registers}.py` + `tests/test_plugin.py`
- `Plugins/io/robot_io/{plugin,registers}.py` + `tests/test_robot_io_plugin.py`
- `Services/device_hub/drivers/robot_driver.py` + `tests/test_robot_driver.py`
- `Services/robot_comm/core/{client,registers}.py`, `server/sim_core.py`,
  `protocols/delta_universal3.yaml`, `tests/test_client.py`
- `Plugins/hub/device_hub/plugin.py`
- `multiprocess_prototype/recipes/hikvision_letter_robot.yaml`

**Прочие в рабочем дереве (ПРЕД-существующая работа pult/robot-place-pose, НЕ эта сессия):**
`Services/control_panel/`, `multiprocess_prototype/.../control_panel/`, `Plugins/processing/crop/`,
`points_render/`, `robot_scale/`, `robot_draw/`, `recipes/phone_sketch.yaml`,
`Services/robot_comm/core/datatypes.py`, `plans/robot-place-pose.md` — разделять при коммите.
