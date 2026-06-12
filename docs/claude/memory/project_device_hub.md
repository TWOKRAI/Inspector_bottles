---
name: project_device_hub
description: "device-hub — always-on процесс устройств, реестр, YAML-протоколы; статус и следующая итерация device-tree-recipe"
metadata:
  node_type: memory
  type: project
  originSessionId: 3eb37597-8be3-47ce-9db9-4f5dcfde7da1
---

Ветка `feat/robot-vfd-services`, продолжение [[project_robot_vfd_services]]. План `plans/device-hub.md` — Фазы 0–5 DONE (2026-06-12) + 2 раунда фиксов по ревью Fable.

**Архитектура:** always-on protected процесс `devices` (base.yaml) владеет ВСЕМИ соединениями. `Services/device_hub` (DeviceManager(BaseManager), драйверы robot/vfd/hikvision/generic_modbus, build_transport tcp|rtu|bridge). `Plugins/hub/device_hub` — 46 команд-алиасов + DeviceHubClient (router_manager.request из worker-потока; send_fire_and_forget для приёмного потока). YAML-протоколы `Services/*/protocols/*.yaml` → RegisterMap+RegisterMeta (`Services/modbus/core/protocol_file.py`), parity-тесты YAML↔python-карты. robot_io тонкий (forward-deque → robot_enqueue_job). vfd_control/robot_draw/runtime.py УДАЛЕНЫ (логика в драйверах).

**Ключевые контракты (из 2 раундов ревью Fable, НЕ ломать):**
- async connect/disconnect: команда отвечает сразу, работа в supervisor-воркере (все команды процесса — в ОДНОМ потоке message_processor!)
- desired-state (`_desired_connected` plugin + driver.desired_connected): disconnect устойчив, реконнект только при desired=True; bridged-VFD реконнектится сам (throttle 3с)
- quality codes good/stale/bad + ts + stats в каждом snapshot; GUI QTimer 2с деградирует по возрасту ts (крэш hub = ручной рестарт, ADR-PH-001 — авто-рестарт protected невозможен by-design)
- DRAW-gating: poll ПЧ приостановлен пока носитель в draw; mode возвращается в cvt после опустошения draw-очереди
- _stop_device_worker → remove_worker (не stop_worker — имя останется занятым)

**Найденные живой проверкой владельца интеграционные баги (диагностированы, НЕ починены):** (1) GuiProcess подписан только на processes.**/system.** — дельты devices.** до GUI НЕ доходят (frontend/process.py:76-83); (2) cmd_device_upsert не зовёт _publish_full_registry; (3) on_add_clicked не подключён в секциях. Урок: qt-mcp probe-smoke ОБЯЗАТЕЛЕН — юнит-тесты с фейками эти разрывы не ловят (см. [[feedback_qt_mcp_smoke_verification]]).

**Следующая итерация — `plans/device-tree-recipe.md` (030152a5, утверждён, исполняет Opus):** решения владельца 2026-06-12: устройства = узлы дерева навигации «Сервисы» (под Камеры/Робот/ПЧ + «+ Добавить устройство» последним), страница устройства = текущие панели; **источник истины — РЕЦЕПТ** (top-level devices:, RecipeDevicesStore поверх read_raw/save_raw, команда device_sync_set при активации); devices.yaml упраздняется; автопоиск камер на странице добавления (hik_enum), робот/ПЧ — ручной ввод. Нужен rebuild_tree() в BaseTreeNavTab (динамики в дереве нет). Верификация — строго через qt-probe + чек-лист железа в плане.
