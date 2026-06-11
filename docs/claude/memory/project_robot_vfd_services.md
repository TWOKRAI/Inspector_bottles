---
name: project_robot_vfd_services
description: Сервисы Робот Delta + ПЧ GD20 из robot/universal3 — универсальный modbus + мост через Protocol
metadata:
  node_type: memory
  type: project
  originSessionId: 3eb37597-8be3-47ce-9db9-4f5dcfde7da1
---

Перенос рабочих программ `robot/universal3/pc_full.py` (+ `cvt_universal_full.lua`) в прототип как переиспользуемые сервисы устройств. Ветка `feat/robot-vfd-services`, план `plans/robot-vfd-services.md`. Фазы 0-5 DONE (2026-06-11), осталось железо + Lua-улучшения.

**Ключевое решение владельца:** `Services/modbus` = универсальный транспортный модуль; сервисы устройств (`robot_comm`, `vfd_comm`, будущие) — тонкие надстройки «выбор соединения + карта регистров + методы». НЕ делать вторую pymodbus-обёртку в каждом сервисе.

**Что добавлено в Services/modbus (фундамент, ADR-MB-001/002):**
- `ModbusDevice.transaction(ops)` — серия записей под одним Lock, **abort на первой ошибке** (маркер-флаг не ляжет поверх частичных данных); примитив mailbox-протоколов
- `RegisterTransport` (Protocol, interfaces.py) — `read_registers`+`transaction`+`is_connected`
- `RegisterMap` (core/register_map.py) — декларативная карта `Reg`/`RegDW`/`RegBlock`+`Field` (scale/signed/word_order) поверх sdk/datatypes
- reconnect — у владельца-плагина, НЕ в sdk (тихий retry разорвал бы атомарность)

**Архитектура моста ПЧ↔робот:** ПК→робот по TCP, робот→ПЧ по RS-485 (Lua ретранслирует mailbox 0x1200→0x1210). `vfd_comm` НЕ импортирует `robot_comm` — зависит от `RegisterTransport`; `RobotClient` его реализует. Связку `VfdClient(transport=runtime.get_client())` делает плагин vfd_control. Завтра прямой RTU = `ModbusDevice(rtu)`+`DIRECT_MAP` без правки клиента.

**Модель владельца соединения (ADR-RC-003):** плагин `robot_io` — ЕДИНСТВЕННЫЙ владелец RobotClient (создаёт/коннектит/публикует в `Services.robot_comm.runtime`/закрывает). Потребители (vfd_control, robot_draw) — `runtime.get_client()`. **Все три плагина обязаны жить в ОДНОМ process_name рецепта** (runtime process-local). `service.py` — карточка каталога БЕЗ соединения (второй TCP-master к mailbox = гонка).

**Карта регистров — ТОЛЬКО universal3** (не u2): CFG=11, TLM=11, DCBUS_SCALE=10, REG_MODE 0x1109, drawing-блок. `WORD_ORDER="little"`, маркер последним, чанки 30/100 при рисовании, unit_id=2.

**КРИТИЧНО (ограничение текущего Lua):** зеркало ПЧ 0x1210+ обновляется ТОЛЬКО при обработке VFD_FLAG → `VfdClient.poll()` пульсирует флаг как poll-триггер + `ensure_alive()` по heartbeat. Команды ПЧ не обслуживаются в DRAW-режиме (GUI дизейблит VFD-кнопки в DRAW).

**Симулятор (ADR-RC-004):** `RobotSimCore` (чистая логика Lua Motion-цикла) → `FakeRobotTransport` (in-process, ~90% тестов) + TCP `sim_robot` (`python -m Services.robot_comm.server`, через хук `SimDevice(action=)` pymodbus 3.13 — классический datastore удалён).

**Объём:** 251 пакетный тест + 3363 framework зелёные. Рецепт `recipes/robot_demo.yaml`. GUI — вкладка Services → «Робот Delta».

Калибровка pixel→robot — отдельный план [[project ничего]] `plans/robot-calibration.md` (синхронизирован: строится поверх готовой инфраструктуры, robot_io расширяется а не создаётся). Связано с командами через RouterManager — см. [[project_backend_control_mcp]].
