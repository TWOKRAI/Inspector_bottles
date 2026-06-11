# robot_comm — статус

**Дата:** 2026-06-11 · **Статус:** ✅ Фаза 1 готова (клиент + sim + CLI)

## Сделано

- [x] Карта регистров universal3 (`core/registers.py`) — один источник истины,
  DW-выравнивание валидируется
- [x] `RobotClient` поверх `ModbusDevice.transaction` (порт `pc_full.py`):
  CVT (send_job/is_free/echo/stop/servo), телеметрия, конфиг (RMW + маркер),
  рисование (circle/polyline, чанки 30/100), мост `RegisterTransport`
- [x] `RobotSimCore` — чистая логика фейк-робота (Motion-цикл поллинга флагов,
  зеркало ПЧ с heartbeat-семантикой реального Lua)
- [x] `FakeRobotTransport` (in-process) + TCP `sim_robot` (SimDevice action-хук,
  pymodbus 3.13) — одно ядро
- [x] ~~`runtime.py`~~ — удалён; владелец соединения — процесс `devices` (ADR-DH-001)
- [x] `service.py` — карточка каталога БЕЗ соединения
- [x] CLI: pos/enc/cal/state/params/echo/job/mode
- [x] Тесты: 40 (fake + TCP e2e)

## Не сделано / дальше

- [x] ~~Плагины robot_io / robot_draw~~ → robot_io тонкий (job-форвард), robot_draw удалён (логика в RobotDriver)
- [ ] Проверка на железе (`python -m Services.robot_comm pos` → X,Y,Z)
- [ ] Lua-улучшения (idle-публикация ПЧ, PROTO_VERSION, ack/seq) — по плану

## Зависимости

`Services.modbus` (transaction/RegisterMap/RegisterTransport); pymodbus — opt
(`[modbus]`), без неё работают карта/кодеки/fake/sim_core (`ROBOT_AVAILABLE=False`).
