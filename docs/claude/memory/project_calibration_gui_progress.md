---
name: project-calibration-gui-progress
description: Калибровка камера↔робот — WIP-баг прогресса визарда (GUI не подписан на calibration.**) ПОЧИНЕН; урок про новые state-корни
metadata:
  type: project
---

Визард калибровки (Services→Робот→под-вкладка «Калибровка», плагин `camera_robot_calibration`) публикует прогресс в state-корень `calibration.state.<camera_id>.progress`. `GuiProcess._init_application_threads` (multiprocess_prototype/frontend/process.py) подписывается на **фиксированный список** корней: `processes.**`, `system.**`, `devices.**` — и теперь `calibration.**`.

**Урок (reusable, главное):** плагин, публикующий в НОВЫЙ state-корень, НЕ достигнет GUI, пока в `GuiProcess` не добавлен `self._gui_state_proxy.subscribe("<root>.**", lambda _d: None, exclude_self=True)`. DeltaDispatcher шлёт дельты только подписчикам; GUI не в списке → `bind_fanout` молчит, виджеты «висят» на оптимистичных локальных статусах. При этом бэкенд полностью рабочий — легко принять за «вся фича не работает».

**Why:** баг был ровно этим. «3 известных GUI-бага» из WIP-коммита 37d4fc28 = 3 проявления ОДНОГО корня (не обновлялись «найдено N/5», «собрано i/5», reproj+активация «Сохранить»).

**How to apply:** при добавлении плагина с `ctx.state_proxy.set("<новый_корень>...")` — сразу добавь подписку в process.py и расширь тест `test_gui_process.py::test_subscriptions_*`.

Фикс: ветка `fix/calibration-gui-progress` (b9fbbde1) — 1 строка подписки + регресс-тест. Бэкенд калибровки доказан здоровым: 47 тестов (вкл. sim-integration с pymodbus) + headless-прогон через `backend_ctl.BackendDriver` на живом симуляторе робота (`send_command("cal", "cal_*", …)` приняты + `state.get("calibration.state.cam0.progress")` вернул прогресс + vfd-мост к sim рабочий).

Отдельная framework-находка (НЕ чинил, benign): в мультиплагинном процессе generic-команда `set_config` коллизирует — `plugins/base.py:474` авто-регистрирует её у каждого плагина с `register_class`, у 2-го/3-го не регистрируется (лог `detector`: «Handler 'set_config' already exists»). Live-тюнинг из GUI идёт через `register_update` (process-level, без коллизии), поэтому это лишь шум в логе.

Техника проверки: `BACKEND_CTL=1 run.py <recipe>` → `backend_ctl.BackendDriver(port=8765)` шлёт команды процессам и читает дерево через `state.get` (target `ProcessManager`) — headless-драйв и верификация без GUI/qt-mcp. Related: [[project_backend_control_mcp]], [[project_telemetry_subscription_bug]], [[project_telemetry_self_publish]], [[reference_qt_mcp_launch]].

**ОБНОВЛЕНИЕ 2026-06-14 (handoff `docs/handoffs/2026-06-14_camera-robot-calibration.md`):** pull-команда device-hub `robot_get_telemetry` через `DeviceHubClient.request` возвращает ПУСТОЙ `{'status':'ok'}` — payload (telemetry/encoder) теряется на уровне IPC-ответа hub-команды (НЕ Lua, НЕ формат: ключи `to_dict()`=`x_mm/y_mm` верные). Ручная вкладка робота «работает» через **push** `devices.state.<id>.status` (`bind_fanout`), а не pull — её «Обновить» тоже пустой, push маскирует. **Решение:** калибровка берёт координаты робота с GUI-стороны из того же push (`_on_robot_status` в calibration/controller.py) и пишет через `cal_set_point(index, px=live_px[i], mm, enc)` — сломанный `cal_set_robot_point`/`_read_telemetry` НЕ используется. Калибровка стала belt-optional (compute без encoder_scale). IPC-баг pull (теряет payload) НЕ починен, обойдён — отдельно расследовать device_hub plugin/client + router_manager. Вся сессия НЕ закоммичена (21 файл + morphology-плагин + wheel-guard + снимок дисплея + bypass-нод).
