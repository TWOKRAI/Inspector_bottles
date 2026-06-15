---
name: project_pult_control_panel
description: Сервис «Пульт» (control_panel) + дашборд (управление полями/сигналами других нод) + узел robot_scale (px→мм)
metadata:
  type: project
---

Ветка `feat/pult-control-panel`. План `plans/pult-control-panel.md`.

**Сервис «Пульт» (`Services/control_panel/` + GUI-вкладка Services «Пульт»):** рецептный — контролы хранятся в config-поле `controls` ноды `control_panel` (source-плагин, пул портов out_1..out_8). Phase 1-3 DONE + qt-mcp smoke. Контролы: button/toggle/slider/number/text эмитят значение на свой порт (pipeline-сигнал), привязываются к потребителю в редакторе Pipeline. add/remove персистятся в рецепт через `SetPluginConfig` (editor-топология → save). Демо `recipes/pult_demo.yaml`.

**Грабли (smoke поймал):** секция Services ОБЯЗАНА реализовать `action_buttons()` — иначе весь Services-таб падает «Ошибка загрузки» (unit-тест спеки не ловит; есть регресс-тест на поверхность SectionProtocol). qt-mcp дерево-навигация ненадёжна по координатам — кликать прямой ref видимого элемента после End-скролла.

**Кнопка «Рисовать» в phone_sketch (DONE, verified live):** пульт-сигнал out_1 → провод → `robot_draw`. robot_draw получил generic pipeline-триггер: register `trigger_source` (ключ сигнала = имя ИСХОДНОГО порта, провода НЕ переименовывают ключ!) + входной порт `trigger`; сигнал взводит `_armed` (как cmd_send), путь уходит на ближайшем кадре с draw_points. Сигнал и draw_points приходят в РАЗНЫЕ process()-вызовы (chain_targets маршрутизирует, не wires). Универсально: любой контрол вяжется к роботу конфигом, без правок кода.

**Направление «дашборд» (Phase 5, в работе):** вынести в пульт ТОЛЬКО ВЫБРАННЫЕ параметры/сигналы ДРУГИХ нод (GUI-пикер «Добавить из ноды»), чтобы настраивать нужное в одном месте. `ControlSpec.source ∈ {local,param,monitor,action}` + target_process/target_field/target_command (Phase 5.1 DONE). Переиспользует: param→live field-write (`SetPluginConfig`→`register_update`, app.py listener), action→`bridge.on_action_command`, monitor→state-bind. Осталось 5.2 роутинг presenter, 5.3 GUI-пикер (поля из registers_manager), 5.4 monitor, smoke.

**Робот-параметры для дашборда (разведка):** pen_up/pen_down/draw_speed_pct — НЕ register-поля, живут в RobotDriver (процесс `devices`), меняются вживую готовыми командами device_hub `robot_draw_set_pen`/`robot_draw_set_speed`/`robot_set_robot_config` (speed/overdrive CVT), GUI уже есть в RobotPresenter.set_pen/set_draw_speed. Масштаб под лист — register-поля strokes_to_points (zone_mode/zone_x0..y1, live-tunable).

**Узел `robot_scale` (DONE, `Plugins/processing/robot_scale/`):** по курсу владельца — strokes_to_points оставляем в ПИКСЕЛЯХ, отдельный узел `robot_scale` вписывает кадр в прямоугольник листа по углам ЛВ(x0,y0)/ПН(x1,y1) мм (формула `x0+px*(x1-x0)/src_width`). Register-поля live-tunable → target дашборда. NEXT: вписать в phone_sketch (strokes→identity scale=1/flip=false + вставить robot_scale + углы) + смоук; затем дашборд-GUI.

Связано: [[project_phone_gateway_service]], [[project_device_hub]], [[project_robot_vfd_services]].
