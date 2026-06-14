---
date: 2026-06-14
topic: Калибровка камера↔робот — режим, маска красного, координаты точек, телеметрия
machine: Windows
branch: main
---

## Session goal
Включить/довести режим калибровки камера↔робот в активном прототипе: чистая маска
красных точек, 5 кругов, нумерация точек на кадре, поля px+робот-координат (правка
вручную), кнопка пишет координаты робота. Плюс попутные UX/инфра-фичи.

## Done (всё НЕ закоммичено — 21 файл + 2 новых, см. ниже)
- **Новый плагин `morphology`** (`Plugins/processing/morphology/`) — open/close/erode/dilate
  бинарной маски (вырезает только круги, чистит шум). +тесты, ruff чисто.
- **`contour_finder` += `keep_mask`** — отдаёт чистую маску на дисплей.
- **bypass-нод (framework)**: `ProcessModulePlugin.enabled` + проверка в `PluginRunner.call_process`
  (выключенная нода пропускает кадр) + команда `set_enabled` в `PluginOrchestrator` +
  чекбокс «Нода включена» в инспекторе Pipeline. +тесты.
- **wheel-guard** (`frontend/wheel_guard.py`) — колесо мыши НЕ меняет значения spin/combo/slider
  глобально (event filter в `app.py`); прокрутка страниц сохранена. +тесты.
- **Снимок дисплея**: кнопка «Снимок» во вкладке Displays → PNG в `data/snapshots/`
  (грабит полный кадр из `ImagePanelWidget.grab_frame`; `image_panel` прокинут через RuntimeDeps).
- **Рецепт `camera_robot_calibration` активирован** (`app.yaml`), ROI=413/120/734/846,
  цепочка `color_convert(bgr2rgb) → hsv_mask(H95-135) → morphology → contour_finder`,
  робот реальный `192.168.1.7:502`.
- **`dataset_circle_capture`** — оставлен для датасета (с `line_filter`).
- **Калибровка-плагин**: нумерация live-точек 1-5 на кадре (`order_points`), снапшот
  += `px`/`live_px`/`mm`/`roles`, периодическая публикация из воркера (real-time px),
  команда `cal_set_point(index, px, mm, enc)` (ручная правка/GUI-запись), compute
  работает БЕЗ ленты (статическая калибровка), `_read_telemetry` устойчив к вложенности.
- **Виджет калибровки**: 5 строк [Точка N][px X/Y][робот X/Y] редактируемые; убраны
  кнопки «Снять кадр» и «Начать сессию»; Camera/VFD → editable QComboBox; метка
  «Робот сейчас: X/Y/энкодер» (live).

## What did NOT work (ВАЖНО — не копать заново)
- **pull `robot_get_telemetry` возвращает пустой `{'status':'ok'}`** — данные (telemetry/encoder)
  теряются на уровне IPC-ответа device-hub команды. Из-за этого калибровка-плагин,
  читавший телеметрию через `DeviceHubClient.request` (`_read_telemetry`), падал
  «Телеметрия робота без x_mm/y_mm/encoder». Диагностика подтвердила: ответ реально пустой.
- **Ручная вкладка робота «работает» НЕ через pull**, а через **push** `devices.state.<id>.status`
  (подписка `bind_fanout`) — там `telemetry{x_mm,y_mm,…}` + `encoder` присутствуют.
  Её кнопка «Обновить» (pull) тоже пустая — просто push маскирует.
- **НЕ Lua и НЕ формат телеметрии**: `robot/universal3/cvt_universal_full.lua` пишет полный
  блок 0x1130 в idle-ветке CVT; ключи `to_dict()` = `x_mm/y_mm` совпадают с тем, что ждёт cal.
  Менять Lua НЕ нужно.
- Робастный фикс cal-side `_read_telemetry` (доставать из result/data + encoder optional)
  НЕ помог, т.к. ответ пуст целиком (`{'status':'ok'}`).

## Key decisions made
- **Обходим сломанный pull**: координаты робота берём с GUI-стороны из того же push
  (`devices.state.<robot_id>.status`), который рабочий. «Точка N» больше НЕ зовёт
  `cal_set_robot_point`; контроллер шлёт `cal_set_point(index, px=live_px[i], mm=[x,y], enc)`.
  Реализовано в этой сессии (controller/presenter/plugin), 55 тестов passed, ruff чисто.
- Calibration сделана belt-optional (compute без `encoder_scale` = статическая калибровка).
- `dataset_circle_capture` = датасет (line_filter), `camera_robot_calibration` = калибровка (без line).

## Next step
Перезапустить прототип (`python multiprocess_prototype/run.py`) и проверить на ЖИВОМ роботе:
выбрать робота → метка «Робот сейчас» должна показывать X/Y/энкодер (push); навести плату
(live 5/5) → жать «Точка N» по номерам → поля «робот X/Y» должны заполниться, «Собрано i/5»
расти; затем «Вычислить» (без ленты) → «Сохранить». Если «Робот сейчас» пустая — копать
публикацию `devices.state.robot_main.status` в процессе devices (а НЕ pull-команду).

## Files changed
Modified (21): Plugins/calibration/camera_robot/{plugin.py,tests/test_plugin.py},
Plugins/processing/contour_finder/{plugin.py,registers.py},
multiprocess_framework/modules/process_module/generic/{plugin_orchestrator.py,plugin_runner.py},
multiprocess_framework/modules/process_module/plugins/base.py,
multiprocess_framework/modules/process_module/tests/test_plugin_runner.py,
multiprocess_prototype/app.yaml, multiprocess_prototype/frontend/{app.py,runtime_deps.py},
multiprocess_prototype/frontend/widgets/image_panel/{presenter.py,widget.py},
multiprocess_prototype/frontend/widgets/tabs/displays/tab.py,
multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py,
multiprocess_prototype/frontend/widgets/tabs/services/robot/calibration/{controller.py,presenter.py,widget.py,tests/test_calibration_controller.py},
multiprocess_prototype/recipes/{camera_robot_calibration.yaml,dataset_circle_capture.yaml}.
Untracked (4): Plugins/processing/morphology/, multiprocess_prototype/frontend/wheel_guard.py,
multiprocess_prototype/frontend/tests/test_wheel_guard.py, config/ (config/calibration/target_5dots.png).

## Открытые долги / заметки
- IPC-баг pull device-hub команд (теряют payload) — НЕ починен, обойдён. Стоит отдельно
  расследовать (investigator) с логами в процессе devices: что возвращает handler vs что
  доезжает до `router.request`. Файлы: `Plugins/hub/device_hub/{plugin.py,client.py}`,
  `Services/device_hub/{manager.py,drivers/robot_driver.py}`,
  `multiprocess_framework/modules/router_module/core/router_manager.py`.
- Дропдауны Camera/VFD сейчас editable-combo с дефолтами (cam0/vfd_belt); реальное
  наполнение списком (камеры из рецепта, ПЧ из devices) НЕ подключено — есть сеттеры
  `widget.set_camera_options()/set_vfd_options()`, их надо звать из robot `section.py` с services.
- Всё НЕ закоммичено. Перед коммитом — формат с trailers Why:/Layer: (см. CLAUDE.md).
  Логично разбить: morphology / contour_finder+recipe / bypass / wheel-guard / снимок-дисплея /
  калибровка-координаты+телеметрия.
