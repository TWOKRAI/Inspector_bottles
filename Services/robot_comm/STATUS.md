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
- [x] `SimJournal` + окно-монитор обмена (`--gui`): две колонки «принято от ПК ↔
  отдал робот», детектор повторных заданий по инварианту трекинга ленты
- [x] Реалистичный тайминг симулятора (`--job-ms`/`--accept-ms`/`--belt-mm-s`):
  на прежних 20 мс дефект «одна деталь → три задания» не воспроизводился
- [x] `BeltDrive` (`server/belt.py`, line-sim Task 2.1) — модель ленты:
  команда ПЧ (mailbox 0x1200..0x1204) → мм/с → отсчёты энкодера; дробный
  остаток копится между тиками (низкая скорость больше не «тихо» округляется
  в 0 и не в 1 отсчёт/тик). `RobotSimCore` принимает ленту через конструктор
  (`belt=`); без инъекции — `BeltDrive.from_enc_rate(enc_rate, ...)`
  воспроизводит старое поведение побитово. `--belt-mm-s` в CLI теперь строит
  `BeltDrive`, и лента едет только по живой команде ПЧ (как настоящий
  конвейер без пуска), а не всегда с постоянной скоростью
- [x] Тесты: 144 (fake + TCP e2e + журнал + окно + BeltDrive); детектор дублей
  проверен инъекциями поломок — каждый тест краснеет от своей
- [x] T2.W (протокол v2, отладочный вид) — стрелка RZ в `SimView` +
  `ZScale`/`TimeTape` (`gui/z_view.py`); заменяется виджетами GUI-конструктора в Ф6

- [x] `build_fw.py` — сборщик прошивки `robot/v2/src/NN_*.lua` -> `robot/v2/main_v2.lua` (T1.3, robot-protocol-v2)
- [x] Программы робота (T3.3, robot-protocol-v2): `programs/program.py` — `Point`/`FrameDef`/`Move`/`Action`/`Program`, `compile_program` -> `Scenario` с картой «запись -> шаг» (ADR-RC-018); без клиента v2 сценарий ещё не грузится в робота
- [x] `RobotClientV2` (`core/client_v2.py`, T3.1, robot-protocol-v2): probe, mailbox-транзакция, `wait_done`, `poll_errors`, стоп с seq (О5),
  пульс/поводок, `sync_params` по метке; ошибки в `errors.py`; тесты автора `test_client_v2.py` + слепая приёмка `test_client_v2_acceptance.py`.
  Не сделано: драйвер v2 и расписание пульса (T5.1), e2e клиент↔sim (T3.5)
- [x] Обёртки опкодов и пинг-понг сценария (T3.2, robot-protocol-v2): `RobotClientV2.WRAPPERS` + метод на каждый опкод,
  `core/wire_v2.py` (кодировщик с шагом `round_step` и повторной проверкой зоны после округления, нарезка на куски по
  EXACT), `upload` блоками FC16, `run_chunks` с меткой стопа -> `RunReport`; тесты автора `test_client_v2_chunks.py` +
  слепая приёмка `test_client_v2_chunks_acceptance.py` (golden `tests/golden/t32_run_chunks.log`).
  Не сделано: пульс в `run_chunks` (поток вызывающего, T5.1), путь GUI -> `round_step` (T5.1/T6.1)
- [x] Ленивые `__init__` корня и `core/` (T3.6, PEP 562): `import Services.robot_comm.programs` не грузит pymodbus,
  `Services.modbus`, `core.client`; имена `__all__` прежние (приёмка `test_lazy_init_acceptance.py`). Остаётся
  `multiprocess_framework` через `params_v2` (≈ 0,7 с) — вне объёма по слову владельца
- [x] Генераторы программ (T3.4, robot-protocol-v2): `programs/generators/` — `draw` (штрихи -> программа, правило 26),
  `circle_stroke`/`square_stroke` (полилинии, О-4), `return_slot` (v1 RETURN), `toolchange` (v1 TOOLCHANGE, через «над 1»);
  выход `GeneratedProgram(program, points)` для `compile_program`; тесты автора `test_generators.py` + слепая приёмка
  `test_generators_acceptance.py`. Не сделано: паритет «RETURN/TOOLCHANGE кончаются домом» — драйвер T5.1

## Не сделано / дальше

- [x] ~~Плагины robot_io / robot_draw~~ → robot_io тонкий (job-форвард), robot_draw удалён (логика в RobotDriver)
- [ ] Проверка на железе (`python -m Services.robot_comm pos` → X,Y,Z)
- [ ] Lua-улучшения (idle-публикация ПЧ, PROTO_VERSION, ack/seq) — по плану

## Зависимости

`Services.modbus` (transaction/RegisterMap/RegisterTransport); pymodbus — opt
(`[modbus]`), без неё работают карта/кодеки/fake/sim_core (`ROBOT_AVAILABLE=False`).
