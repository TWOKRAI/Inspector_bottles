# План: Протокол робота v2 — единый mailbox, сценарии, параметры, GUI-панель

- **Slug:** `robot-protocol-v2`
- **Ветка:** `feat/robot-protocol-v2` (от свежего `main`)
- **Статус:** утверждён владельцем 2026-07-19; исполнение — по отдельной команде
- **Дата:** 2026-07-19
- **Refs:** ревью прошивки 2026-07-19 (сессия), независимое ревью плана (APPROVE с правками, все 10 внесены)
- **Сопутствующие документы:** [tasks.md](tasks.md) — детальные брифы задач для агентов (Opus 4.8 / Sonnet 5); [protocol-spec.md](protocol-spec.md) — полная спецификация протокола v2; [firmware-architecture.md](firmware-architecture.md) — архитектура прошивки

## Контекст

Прошивка `robot/main_actual.lua` (Delta SCARA, DRAStudio/Lua) выросла в 5 ad-hoc режимов (CVT/DRAW/MANUAL/RETURN/TOOLCHANGE) с зоопарком flag/busy-регистров. Ревью 2026-07-19 нашло 10+ реальных багов (утечка Override между режимами, мёртвый REG_DRAW_SPD, рассинхрон состояния инструмента, Mirror без pcall, отсутствие валидации координат и канала ошибок, нет watchdog ПК). Карта регистров существует в 4 рукописных копиях (Lua, `registers.py`, YAML, офсеты `sim_core.py`) + эталон `pc_full.py`. Владелец решил: редизайн протокола v2 — командный mailbox («лесенка» opcode→args→flag), генерализация рисования в сценарный режим, параметрический словарь, чистый разрыв с v1, прошивка «как можно лучше», GUI-панель настройки — в этом же плане.

**Канон прошивки:** `robot/main_actual.lua` ≡ `robot/universal3/cvt_universal_full.lua` (различие — CRLF + 6 строк; тесты паритета ссылаются на universal3-файл). Канон для Ф4 (донор VFD-моста и CVT-механики) — `robot/main_actual.lua`.

**Решения владельца (не пересматривать):**
1. Режимы v2: IDLE / PTP / JOG / CVT_TRACK / SCENARIO. RETURN и TOOLCHANGE — больше не прошивочные режимы, а сценарии (точки+действия присылает ПК).
2. Все команды через единый mailbox с seq/ACK/NAK+errno. Вне mailbox — только телеметрия (read-only) и bulk-буфер точек.
3. Чистый разрыв: v1-прошивка замораживается как fallback, новая карта, эталон паритета обновляется.
4. Объём: протокол + прошивка + sim + клиент + драйвер/плагины + GUI-панель параметров с teach-захватом точек.
5. Прошивка v2 — чистовая переработка с закрытием всех находок ревью by design.
6. Полноценная Python-имитация робота для работы без железа (усиленная Ф2).

**Независимое ревью плана (2026-07-19): APPROVE с правками — все 10 внесены.** Ключевая честность: оценки «после» по machine-safety (3→8) и корректности (4→7) — *by design*; поведенчески они подтверждаются только на Ф7 (железо). До Ф7 единственный hardware-проверенный якорь — зелёный v1-паритет `test_parity_universal3.py`.

## Архитектура v2 (сводка)

**Три плоскости:** командная (mailbox CMD/RES), параметрическая (словарь id→значение, opcodes PARAM_SET/GET + read-only зеркало для чтения одним FC3), данных (буфер точек сценария + телеметрия + heartbeat).

**Режим не задаётся, а выводится:** opcode определяет активность; `TLM_ACTIVITY` — read-only. Ликвидирует гонки «смена режима при busy» и elseif-лестницу ×4. CVT — одноразовая активность `CVT_JOB` (pick+ecap+place в одной команде), между заданиями IDLE.

### Карта регистров

```
0x1000..0x100F  CMD:  FLAG(0x1000, ПК пишет 1 последним отдельным FC6), SEQ(1..65535),
                      OPCODE, ARGC, ARG0..ARG11 (ARG0=0x1004 чётный — DW-аргументы на чётных слотах)
0x1010..0x101F  RES:  SEQ-эхо (прошивка пишет ПОСЛЕДНИМ), STATUS(1 ACK/2 NAK), ERRNO, RVALC, RVAL0..7
0x1020          HB_PC — heartbeat ПК (watchdog-kick, вне mailbox)
0x1040..0x107F  TLM (26 рег, один FC3): PROTO_VER(0x1040=0x0200), FW_BUILD, HB_ROBOT, ACTIVITY,
                X/Y/Z/RZ, MOVING, SERVO, SPD_PCT, GRIP, ENC(DW 0x104C чётный), BELT, WDG_STATE,
                ACK_SEQ, DONE_SEQ, ERR_SEQ, ERRNO_LAST, ERR_COUNT, SC_ID/TOTAL/INDEX/DONE_N, MISS_COUNT
0x1200..0x121F  VFD-mailbox — ЗАМОРОЖЕН (принадлежит Services/vfd_comm), тест на непересечение
0x1300..0x137F  PMIR — read-only зеркало параметров (адрес = 0x1300+id; чтение по факт. max id ≤125 рег)
0x1400..0x16FF  SC — буфер сценария: 96 записей × 8 рег; резерв 0x1700..0x17FF
```

Инварианты: DW на чётных адресах; блочная запись ≤30 рег; маркер (CMD_FLAG / RES_SEQ) пишется последним; **клиент обязан выполнить PROTO_VER-probe до любых записей** (защита от залитой v1-прошивки: на v1 адрес 0x1040 читается 0).

⚠️ **Гейт карты (правка ревью):** проверенный на железе максимум адресов — 0x154B; SC-буфер (0x1400..0x16FF) И даже fallback SC_CAP=64 (до 0x15FF) стоят на непроверенном пространстве. **Проба адресного потолка DRAS обязательна ДО заморозки карты в Ф2** (разовый визит к железу после Ф1). Если потолок < 0x16FF — SC_CAP пересчитывается под реально доступное ДО генерации golden (в проверенное пространство влезает ~41 запись — при нехватке пересматривается stride).

### Запись сценарной точки (stride 8)

```
+0 X  +1 Y  +2 Z (s16 ×0.1мм)   +3 RZ (s16 ×0.1°)
+4 KIND:   0 LINE (MovL, точный стоп) / 1 LINE_PASS (MovL+PASS) / 2 JOINT (MovP)
+5 ACTION: 0 NONE / 1 DO_ON / 2 DO_OFF / 3 DELAY_MS / 4 SPEED_PCT / 5 ACCEL_MMSS
+6 APARAM  (канал DO / мс / % / мм/с²)     +7 резерв
```

Действие исполняется ПОСЛЕ прихода в точку («до движения» = дубль-точка). Прошивка не знает про «перо»: П-образные переезды, высоты, grip-паузы генерирует ПК. Прогресс `TLM_SC_INDEX` пишется только на EXACT-точках (KIND≠LINE_PASS) — PASS-блендинг не рвётся (инвариант v1 сохранён by design).

### Opcodes / errno

| Opcode | Аргументы | Семантика |
|---|---|---|
| PING 0x01 | — | rvals=[PROTO_VER, FW_BUILD] |
| CLEAR_ERR 0x02 | — | сброс защёлки ERRNO_LAST/ERR_SEQ |
| PTP_MOVE 0x10 | x,y,z,rz,kind,spd_pct | ACK=стартовало; done по TLM_DONE_SEQ |
| HOME 0x11 | — | PTP в P_HOME_* |
| JOG_STEP 0x12 | dx,dy,dz,drz,spd_pct | один относительный ход (абсолютный jog = PTP_MOVE) |
| CVT_JOB 0x20 | ecap(DW на ARG0/1), pick_x/y/z, place_mode, place_x/y/z/rz (argc 10) | трекинг-цикл |
| SC_RUN 0x30 | count, sc_id, start_idx | пред-чтение+валидация ВСЕХ записей до движения |
| STOP 0x40 | level 1 SOFT/2 HARD/3 HARD+HOME/4 ESTOP(+серво OFF+VFD stop) | allow_busy |
| SERVO 0x41 | 0/1 | мгновенно |
| PARAM_SET 0x50 | id, value | валидация min/max → NAK E_RANGE; write-through в зеркало |
| PARAM_GET 0x51 | id | rval0=value |

Errno: `E_OK, E_BAD_OPCODE, E_BAD_ARGC, E_RANGE, E_BUSY, E_BAD_PARAM, E_NO_SERVO, E_SC_COUNT, E_SC_RECORD, E_BUF_SHORT, E_WDG_TIMEOUT, E_MOTION_FAULT, E_ZONE_TRIP, E_ABORTED, E_INTERNAL`. Короткое чтение буфера — E_BUF_SHORT (не молчаливое усечение v1). Async-ошибки — через TLM_ERR_SEQ/ERRNO_LAST. Mailbox однослотовый; STOP/PING — allow_busy.

### Словарь параметров v1.0 (id стабильны)

- motion: 0 P_SPD_DEFAULT(80%), 1 P_SPD_JOG(30%), 2 P_ACC_DEFAULT(25000), 3 P_OVERLAP(×0.1мм)
- points: 8..11 P_HOME_X/Y/Z/RZ, 12 P_PICK_Z, 13..16 P_PLACE_X/Y/Z/RZ
- cvt: 20 P_GRIP_MS, 21 P_ZONE_MIN, 22 P_ZONE_MAX
- workspace: 24..29 P_WS_X/Y/Z_MIN/MAX (дефолты — из паспорта SCARA, уточнить в Ф0)
- system: 32 P_WDG_TIMEOUT_MS (0=выкл на bring-up), 33 P_TLM_EVERY, 34 P_DO_GRIP_CH

Пен-высоты/travel-скорость из v1 в словарь НЕ входят — стали данными сценария. Персистентность — на ПК (`data/devices.yaml`, push-on-connect).

### Watchdog

ПК-драйвер инкрементирует HB_PC каждый tick (период ≤ timeout/4). Прошивка в idle и на EXACT-остановках: HB не менялся дольше P_WDG_TIMEOUT_MS → стоп ПЧ (мост в прошивке), MotionStop, WDG_STATE=2, async E_WDG_TIMEOUT, ACTIVITY→IDLE.

⚠️ **Часы (правка ревью):** боевой watchdog требует реального времени (Systime DRAS). Fallback «счётчик итераций ×2» — ТОЛЬКО bring-up-режим: до калибровки часов на железе watchdog считается недоверенным и поставляется выключенным (P_WDG_TIMEOUT_MS=0). Включение — после Ф7-калибровки.

### YAML → кодоген (гибрид)

`Services/robot_comm/protocols/delta_v2.yaml` — единственный источник: `registers:` (в схеме `protocol_file.py` — панель регистров рендерит без правок) + `constants:`, `opcodes:`, `errno:`, `params:` (id/label/unit/scale/min/max/default/group), `scenario:`. Кодоген `Services/robot_comm/codegen.py` → (1) `core/protocol_v2.py` (закоммичен, freshness-тест), (2) Lua-блок констант между маркерами `-- ===== BEGIN/END GENERATED` в прошивке (тест извлекает и сверяет). Все копии карты становятся производными от одного YAML.

## Прошивка v2 — `robot/v2/main_v2.lua`

**Модульность при одном файле (пожелание владельца):** исходники прошивки живут в репозитории МОДУЛЯМИ — `robot/v2/src/NN_имя.lua` (нумерованный порядок сборки), на контроллер уезжает ОДИН собранный артефакт `robot/v2/main_v2.lua`. Сборщик `build_fw.py` (Ф1): конкатенация по порядку + линты (дубли глобалов; запрет `while`/`WAIT`/`DELAY` в секции Mirror; константы кодогена — только ТАБЛИЦАМИ `REG/OP/ERR/PDEF`, т.к. Lua 5.1 ограничен 200 locals на chunk) + вставка GENERATED-блока и FW_BUILD. Артефакт закоммичен, freshness-тест как у `protocol_v2.py`.

Секции (= файлы `src/`): GENERATED-константы → утилиты (nil-safe `rdW/rdDW/wrW` — ВСЕ чтения шины только через них) → VFD-мост (перенос дословно из main_actual.lua) → параметры (таблица P{}, `param_set` с валидацией, зеркало) → безопасность (`in_workspace` для ВСЕХ целей движения, `pending_stop`, wdg) → движок mailbox (диспетчер таблицей `OPS[opcode]={argc, allow_busy, fn}`, pcall, RES всегда пишется, RES_SEQ последним; облегчённый `mb_poll_light` только STOP/PING на EXACT-остановках) → исполнители (`exec_ptp/jog/cvt/scenario`; общие `motion_prologue/epilogue` — восстановление Override/AccL на всех путях выхода; `guarded_move` — stop-check между каждым примитивом; `exec_scenario` — пред-чтение чанками в таблицы, валидация до движения) → Mirror v2 (ОДНА функция: поза, энкодер, peek mailbox на STOP → MotionStop, zone-check при CVT; всё в pcall; без while/WAIT/DELAY) → Motion (`while running: pcall(motion_body)` + recovery: ACTIVITY→IDLE, epilogue, NAK E_INTERNAL) → boot.

**Измеримый критерий «как можно лучше» (приёмка Ф4, правка ревью):** luacheck 0 warnings (со стаб-глобалами DRAS) + **каждая из 10 находок ревью закрыта именованным поведенческим тестом в sim v2** (контракт, не декларация) + построчная сверка по таблице находок: (1)(2)→motion_epilogue+SPEED_PCT-действия; (3)→полный WritePoint X/Y/Z/R; (4)→состояние инструмента на ПК; (5)→pcall в Mirror; (6)→guarded_move; (7)→единый цикл (VFD/телеметрия при любой активности); (8)→in_workspace+E_RANGE/E_SC_RECORD; (9)→rdW/rdDW; (10)→seq-модель вместо busy-флагов + recovery; +NAK-канал, +watchdog, +чистка стейл-комментариев.

## Python-сторона и приложение

- `Services/robot_comm/core/client_v2.py` — `RobotClientV2`: ядро `cmd()` (транзакция args FC16 + флаг FC6, поллинг RES_SEQ, typed-исключения по errno), обёртки, `upload_scenario` (чанки 24 рег = 3 записи), `wait_done(seq)`, `param_read_all` (зеркало одним FC3 по факт. max id), probe PROTO_VER. v1 `client.py` заморожен как fallback.
- `Services/robot_comm/scenarios/` — НОВЫЙ пакет: `model.py` (ScPoint, Scenario, index_map, валидация), `draw.py`, `return_gen.py`, `toolchange.py` (grip = DO_ON + дубль DELAY_MS; teach-точки из devices.yaml). **Уточнение ревью: `draw.py` — это НЕ порт, а перенос firmware-геометрии рисования на ПК**: pen-штрихи → явные П-переезды + Z-высоты + SPEED_PCT-действия (сейчас это делает Lua, строки 524–605 main_actual.lua); из `split_draw_passes` переиспользуется только разбиение по границам штрихов. Здесь живёт качество и безопасность рисования — риск средний, покрывается property-тестами + сравнением на Ф7.
- **Симулятор (усилен по требованию владельца — полная имитация робота без железа):** `server/sim_core_v2.py` — исполняемая спека протокола: mailbox-FSM, словарь параметров с валидацией, сценарный исполнитель с действиями/прогрессом/abort, **линейная интерполяция позы** (X/Y/Z/RZ движутся к цели по скорости за тик — телеметрия показывает «едущего» робота, честные MOVING→DONE-переходы), **явная CVT-модель ленты** (энкодер тикает, забор относительно движущейся ленты), **обязательная wdg-trip-модель** (sim умеет «не получать HB_PC» → E_WDG_TIMEOUT/WDG_STATE=2). Все офсеты — импорт из `protocol_v2.py`. `sim_robot.py --protocol v2` — standalone TCP-slave; **документированный dev-переключатель** «приложение → sim» (devices.yaml host=127.0.0.1:5021) одной строкой. Честная граница: sim гарантирует корректность ПРОТОКОЛА и логики, не физики ДВИЖЕНИЯ (качество рисования/коллизии — только Ф7).
- `Services/device_hub/drivers/robot_driver.py` — **дуальный диспатч (правка ревью): драйвер хранит per-op ОБЕ ветки (v1/v2) с выбором по `devices.yaml params.protocol` — иначе fallback v1 иллюзорен** (в драйвере ~30 ops). Судьба ops: `jog/abort/stop/servo/telemetry/set_robot_config/…` получают v2-адресата (mailbox); `draw_circle/draw_square/draw_polyline` → генерация сценария на ПК; `draw_set_pen/speed/travel/accel/overlap` → PC-side-настройки генератора (в прошивку не ходят). Плюс: push-параметров-on-connect со сверкой по зеркалу, heartbeat в tick, probe при коннекте.
- `Plugins/io/robot_draw/plugin.py` — штрихи → генератор `scenarios.draw`.
- GUI: НОВЫЙ раздел `multiprocess_prototype/frontend/widgets/tabs/services/robot_settings/{widget,presenter,controller,section}.py` — декларативная форма по группам из YAML `params:` (мета через существующий `load_protocol`), запись PARAM_SET с NAK-подсветкой (errno-текст), teach-кнопки «захватить позу». **Правка ревью:** (а) ревизия **33 call-site** старых draw-ops в `multiprocess_prototype/frontend/` (`draw_circle`×12, `draw_square`×9, `draw_set_speed`×9, `draw_set_pen`×2, `draw_set_overlap`×1) → перевод на генерацию сценариев или скрытие при protocol=v2; (б) teach-захват — **расширение существующего `services/robot/calibration/`, не дубль**; (в) диалог подтверждения текущего инструмента при старте (tool-state на ПК).

## Фазы

Ветка `feat/robot-protocol-v2` от свежего `main`. Шаг 0: `docs(plans):`-коммит этого файла. Коммиты — Conventional Commits + `Why:`/`Layer:`/`Refs: plans/robot-protocol-v2/plan.md`. v1-тесты остаются зелёными на всех фазах (fallback жив; v1-паритет — единственный hardware-проверенный якорь до Ф7).

| Ф | Задача | Файлы | Приёмка | Размер |
|---|---|---|---|---|
| Ф0 | Спека+ADR: полный черновик `delta_v2.yaml`; **ADR-RC-009** mailbox+выводимая активность, **-010** YAML→кодоген, **-011** сценарии/tool-state на ПК, **-012** watchdog+seq-модель (006–008 заняты); workspace-лимиты из паспорта SCARA; `python -m scripts.sync` | `plans/…`, `Services/robot_comm/DECISIONS.md`, `protocols/delta_v2.yaml` | ревью YAML владельцем | M |
| Ф1 | Кодоген+инварианты: `codegen.py` → `protocol_v2.py` + Lua-блок; **сборщик прошивки `build_fw.py`** (`src/*.lua` → `main_v2.lua` + линты секций); схемные тесты (непересечение блоков вкл. VFD, DW-чётность, ≤30 рег, стабильность id); толерантность `load_protocol` к новым секциям; **организовать пробу адресного потолка на железе (гейт Ф2)** | `codegen.py`, `build_fw.py`, `core/protocol_v2.py`, `tests/test_codegen_v2.py`, `tests/test_protocol_v2_yaml.py` | freshness-тест; панель регистров рендерит delta_v2.yaml; результат пробы потолка получен | M |
| Ф2 | Симулятор v2 = исполняемая спека (**гейт: карта заморожена только после пробы потолка**): mailbox-FSM, параметры+зеркало, wdg-trip-модель, сценарный исполнитель, интерполяция позы, CVT-модель ленты, standalone `--protocol v2` + dev-переключатель | `server/sim_core_v2.py`, правка `sim_robot.py`, `tests/test_sim_v2_core.py` | юниты на каждый opcode (все ACK/NAK-ветки), wdg-trip, STOP-уровни, сценарии с действиями/прогрессом/abort, интерполяция позы видна в телеметрии | L |
| Ф3a | Клиент v2: ядро cmd/поллинг/errno-исключения, upload_scenario, wait_done, param_read_all, probe; golden wire-лог | `core/client_v2.py`, `tests/test_client_v2.py`, `tests/test_wire_golden_v2.py` | e2e против sim зелёные; golden зафиксирован (**честно: self-referential снапшот, НЕ hardware-эталон — класс гарантии pc_full-паритета восстанавливается на Ф7**) | M–L |
| Ф3b | Генераторы сценариев: model + **перенос firmware-геометрии рисования на ПК** + return + toolchange; property-тесты (index_map биективен, разбиение только по границам штрихов, все координаты в workspace); e2e-циклы | `scenarios/*`, `tests/test_scenarios.py`, `tests/test_sim_e2e_v2.py` (draw 2 прохода, return, toolchange, CVT, wdg, стоп посреди сценария) | e2e зелёные | L |
| Ф4 | Прошивка v2 (параллелима с Ф3): полная чистовая реализация по структуре выше | `robot/v2/src/*.lua` (модули), `robot/v2/main_v2.lua` (собранный артефакт), `robot/v2/README.md` (карта секций + таблица находок), `.luacheckrc` | luacheck 0 warnings; каждая из 10 находок — именованный тест в sim; построчная сверка. **Stretch (вне критического пути): lupa-харнесс** `robot/v2/harness/` — дифф прошивка↔sim | L+ |
| Ф5 | Драйвер и плагины: **дуальный per-op диспатч v1/v2**, судьба 30 ops по списку выше, push-on-connect, heartbeat, probe; robot_draw → генератор | `robot_driver.py`, `Plugins/hub/device_hub/plugin.py`, `Plugins/io/robot_draw/plugin.py`, `data/devices.yaml`, тесты драйвера | приложение против sim v2: рисование из GUI end-to-end; переключение protocol v1↔v2 в devices.yaml работает в обе стороны | M+ |
| Ф6 | GUI: панель `robot_settings` + **ревизия 33 draw-call-site** + **примирение teach с `calibration/`** (расширить, не дублировать) + диалог инструмента | `frontend/widgets/tabs/services/robot_settings/*` + правки существующих + tests (headless, QT_QPA_PLATFORM=offscreen) | форма из YAML-групп; NAK с errno-текстом; teach пишет devices.yaml; старые draw-контролы переведены/скрыты при v2 | M+ |
| Ф7 | Железо (bring-up чек-лист в README) | тюнинг дефолтов → фиксация в YAML | подтверждение потолка адресов, предел FC16, **калибровка Systime → включение watchdog** (до того P_WDG_TIMEOUT_MS=0), PROTO_VER, серво/STOP-уровни/ESTOP, wdg-trip (лента останавливается без ПК), CVT на пустой ленте, **качество рисования v2 vs v1 тем же файлом букв (риск средний)**, toolchange с абортом посередине; инструкция переключения v1↔v2 | M |

Параллелизм: хребет Ф1→Ф2→Ф3a→Ф5 серийный; Ф4 ∥ Ф3; Ф6 стартует после стабилизации YAML-групп (после Ф1) ∥ Ф4/Ф5. Честная оценка масштаба: это многонедельная переработка подсистемы, не фича.

## Верификация

Пирамида: freshness кодогена + схемные инварианты YAML (Ф1) → поведенческая спека sim-юнитами, включая именованные тесты 10 находок (Ф2/Ф4) → e2e клиент↔sim + golden wire-лог (Ф3) → luacheck (+stretch lupa-дифф) (Ф4) → драйверные/presenter-тесты офскрин (Ф5–Ф6) → железный чек-лист (Ф7). Прогоны: `python scripts/validate.py`, pytest из корня; qex-реиндекс после крупных фаз. Работа без железа: всё приложение целиком поднимается против `sim_robot.py --protocol v2` (dev-переключатель в devices.yaml).

## Риски

1. **Потолок Modbus-адресов DRAS** (высокий): даже fallback SC_CAP=64 выше проверенного 0x154B → проба обязательна ДО заморозки карты (гейт Ф2); при потолке 0x154B доступна ~41 запись → пересмотр stride/ёмкости до генерации golden.
2. Атомарность FC16 vs Lua-чтения — нивелирована паттерном «флаг отдельным FC6 последним» (проверен в v1).
3. **Watchdog-часы** (средний): без Systime DRAS боевой watchdog не включается (P_WDG_TIMEOUT_MS=0 до калибровки Ф7).
4. `load_protocol` может не терпеть новые top-level секции — тогда контракт в соседний `delta_v2.contract.yaml`.
5. **Перенос геометрии рисования на ПК** (средний, поднят с «низкого»): П-переезды/высоты/скорости переписываются заново — property-тесты + сравнение тем же файлом букв на Ф7.
6. Latency STOP во время PASS-цепочки = период Mirror (как v1 abort) — не хуже v1.

## Принятые дефолты

- lupa (LuaJIT) харнесс — stretch вне критического пути Ф4.
- Алиасы старых команд device_hub — да.
- Состояние инструмента — на ПК (devices.yaml) + оператор-диалог при неизвестном состоянии.
- Потолок адресов — проба после Ф1 (гейт Ф2); паспортные лимиты зоны — Ф0.
