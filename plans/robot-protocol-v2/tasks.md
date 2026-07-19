# robot-protocol-v2 — детальные задачи для агентов (Opus 4.8 / Sonnet 5)

- **Родительский план:** [plan.md](plan.md) (утверждён владельцем; независимое ревью APPROVE, 10 правок внесены)
- **Ветка:** `feat/robot-protocol-v2` от свежего `main`
- **Статус:** draft — исполнение по команде владельца
- **Справочники:** [protocol-spec.md](protocol-spec.md) — контракт протокола (обязателен для Ф0/Ф2/Ф3/Ф4/Ф5); [firmware-architecture.md](firmware-architecture.md) — архитектура прошивки (настольная книга Ф4)
- **Принцип назначения моделей:** Sonnet 5 — дефолт-исполнитель (бриф буквальный, охват задан явно, ничего «по аналогии»); Opus 4.8 — прошивка, драйвер с конкурентностью, геометрия рисования (сложная семантика). Ревью-финдеры — Sonnet.

---

## 0. Обязательная преамбула каждого брифа (копировать агенту дословно)

1. **Git.** Работать в ветке `feat/robot-protocol-v2`. Параллельные задачи — ТОЛЬКО в отдельных worktree; перед стартом сверить SHA базы worktree с текущим HEAD `feat/robot-protocol-v2` (стейл-база = стоп, доложить). Коммитить каждый законченный шаг.
2. **Коммиты.** Conventional Commits + обязательные trailers:
   `Why:` (мотивация), `Layer:` (из таблицы задачи), `Refs: plans/robot-protocol-v2/plan.md`. Без них hook отклонит коммит.
3. **Тесты.** pytest из корня репозитория; перед коммитом `python scripts/validate.py`. GUI-тесты только с `QT_QPA_PLATFORM=offscreen` (всплывающие окна вешают агентов). Минимум один тест на прод-значениях параметров (не 0, не заглушки — «тест-параметры прячут окно дефекта»).
4. **v1 неприкосновенен.** `core/registers.py`, `core/client.py`, `server/sim_core.py`, v1-тесты, `robot/main_actual.lua`, `robot/universal3/*` НЕ менять (кроме мест, явно перечисленных в задаче). Все v1-тесты зелёные после каждой задачи.
5. **Язык.** Комментарии, докстроки, README — по-русски; идентификаторы — английские.
6. **Контракт первичен.** Все адреса/id/opcodes/errno — только из YAML/кодогена. Рукописный адрес где-либо, кроме `protocols/delta_v2.yaml`, = брак.
7. **Поиск по коду.** «Где используется X» — сначала `mcp__qex__search_code`, потом Grep.

## 1. Архитектурные инварианты (нарушение = возврат задачи)

| # | Инвариант |
|---|---|
| И1 | YAML `protocols/delta_v2.yaml` — единственный источник; `protocol_v2.py` и Lua-блок — только кодогеном |
| И2 | Прошивка: репозиторий = модули `robot/v2/src/NN_имя.lua`; контроллер = один собранный `main_v2.lua`; ручное редактирование артефакта запрещено |
| И3 | Константы кодогена в Lua — только таблицами `REG/OP/ERR/PDEF` (лимит Lua 5.1: 200 locals/chunk) |
| И4 | Mirror-секция: без `while`/`WAIT`/`DELAY` (линт сборщика); всё тело в `pcall` |
| И5 | Маркер последним: `CMD_FLAG` пишет ПК отдельным FC6 в конце транзакции; `RES_SEQ` пишет прошивка/sim последним регистром ответа |
| И6 | Все чтения Modbus в прошивке — через nil-safe `rdW/rdDW`; все цели движения — через `in_workspace` |
| И7 | Python-границы — Dict at Boundary (Pydantic внутри, dict наружу) |
| И8 | Новые коды ошибок/параметры — только через YAML (+ регенерация), не литералами |

## 2. Сводная карта задач

| ID | Задача | Модель | Зависит от | Параллельно с | Размер |
|----|--------|--------|-----------|---------------|--------|
| T-00 | Ветка + фиксация плана и v1-прошивки | оркестратор | — | — | S |
| T0.1 | YAML-контракт delta_v2.yaml | Sonnet | T-00 | — | M |
| T0.2 | ADR-RC-009..012 + sync | Sonnet | T0.1 | — | S |
| GATE-0 | Ревью YAML владельцем | владелец | T0.1–T0.2 | — | — |
| T1.1 | codegen.py → protocol_v2.py + Lua-блок | Sonnet | GATE-0 | — | M |
| T1.2 | Схемные инварианты YAML (тесты) | Sonnet | T1.1 | T1.3 | S |
| T1.3 | build_fw.py — сборщик прошивки | Sonnet | T1.1 | T1.2 | M |
| T1.4 | probe_modbus_ceiling.py + инструкция | Sonnet | T-00 | T1.1 | S |
| GATE-1 | Проба потолка адресов на железе | владелец | T1.4 | — | — |
| T2.1 | sim v2: mailbox-FSM + параметры | Sonnet | T1.1, GATE-1 | Ф4 | M |
| T2.2 | sim v2: движение + интерполяция позы | Sonnet | T2.1 | Ф4 | M |
| T2.3 | sim v2: сценарии + CVT-лента + wdg + standalone | Sonnet | T2.2 | Ф4 | M |
| T3a.1 | client_v2: ядро cmd/поллинг/errno | Sonnet | T2.1 | Ф4 | M |
| T3a.2 | client_v2: обёртки, upload, golden | Sonnet | T3a.1, T2.3 | Ф4 | M |
| T3b.1 | scenarios/model.py + property-тесты | Sonnet | T1.1 | T3a | S–M |
| T3b.2 | scenarios/draw.py — геометрия рисования | **Opus** | T3b.1 | T4.x | M |
| T3b.3 | return_gen + toolchange + e2e | Sonnet | T3b.1, T3a.2 | — | M |
| T4.1 | fw: скелет src/ + util/params/safety | **Opus** | T1.3, GATE-1 | Ф2–Ф3 | M |
| T4.2 | fw: движок mailbox | **Opus** | T4.1 | Ф2–Ф3 | M |
| T4.3 | fw: исполнители движения | **Opus** | T4.2 | Ф3 | L |
| T4.4 | fw: VFD-мост, Mirror, Motion, boot | **Opus** | T4.3 | Ф3 | M |
| T4.5 | fw: README + чек-лист железа | Sonnet | T4.4 | T4.6 | S |
| T4.6 | Именованные тесты 10 находок (контракт) | Sonnet | T2.3, T4.4 | T4.5 | M |
| T4.7 | (stretch) lupa-харнесс прошивки | **Opus** | T4.4 | — | M |
| REVIEW-4 | Формальное /code-review прошивки | Opus + Sonnet-финдеры | T4.4–T4.6 | — | — |
| T5.1 | Драйвер: дуальный диспатч v1/v2 + push/heartbeat/probe | **Opus** | T3a.2 | T6.1 | L |
| T5.2 | device_hub команды + robot_draw → генератор | Sonnet | T5.1, T3b.3 | — | M |
| T5.3 | Тесты драйвера (v1-регресс + v2 против sim) | Sonnet | T5.1–T5.2 | — | M |
| REVIEW-5 | Формальное /code-review драйвера | Opus + Sonnet-финдеры | T5.1–T5.3 | — | — |
| T6.1 | GUI: панель robot_settings (декларативная форма) | Sonnet | T1.1 (мета), T5.1 | T5.2 | M |
| T6.2 | GUI: ревизия 33 draw-call-site | Sonnet | T5.2 | T6.3 | M |
| T6.3 | GUI: teach в calibration/ + диалог инструмента | Sonnet | T5.1 | T6.2 | M |
| T6.4 | GUI-тесты (offscreen) | Sonnet | T6.1–T6.3 | — | S–M |
| REVIEW-6 | Лёгкое групповое ревью GUI | Sonnet | T6.x | — | — |
| Ф7 | Bring-up на железе по чек-листу T4.5 | владелец + live-агент | всё | — | M |

**Merge-политика:** задачи коммитятся в `feat/robot-protocol-v2`. В `main` — тремя milestone (каждый через формальное ревью): M1 после Ф2 (контракт+sim), M2 после REVIEW-5 (вся ПК-сторона против sim), M3 после Ф7 (железо подтверждено). Прошивка v2 в main до железа — допустимо (файлы никому не мешают, v1 — рабочий канон до M3).

**Параллельность:** не более 2–3 агентов одновременно; прошивка (Ф4) — ОДИН Opus-агент в отдельном worktree последовательными коммитами (несколько агентов на один артефакт = склейка коммитов, запрещено).

---

## 3. Детальные брифы

### T-00 — Ветка + фиксация исходников (оркестратор, Layer: docs)

1. `git checkout main && git pull` → `git checkout -b feat/robot-protocol-v2`.
2. Коммит 1 `docs(plans)`: `plans/robot-protocol-v2/plan.md` + `tasks.md`.
3. Коммит 2 `docs(robot)`: зафиксировать untracked `robot/main_actual.lua` (канон v1-прошивки, сейчас НЕ в git — риск потери).
Приёмка: `git log --oneline -2` показывает оба коммита; hook принял trailers.

### T0.1 — YAML-контракт (Sonnet, Layer: services)

**Файл (создать):** `Services/robot_comm/protocols/delta_v2.yaml`.
**Сделать:**
- Секция `registers:` — СТРОГО в схеме существующего загрузчика (`Services/modbus/core/protocol_file.py:load_protocol`; образец стиля — `delta_universal3.yaml`): все регистры из plan.md §«Карта регистров» (CMD 0x1000.., RES 0x1010.., HB_PC 0x1020, TLM 0x1040.., PMIR 0x1300.., SC 0x1400..) с `label`/`hint`/`unit`/`scale`/`signed`/`access` по каждому. Источник значений — [protocol-spec.md](protocol-spec.md) §2/§4/§5/§6/§7 (полные таблицы; plan.md — сводка); перенос 1:1, расхождение = дефект. VFD-блок 0x1200..0x121F в registers НЕ включать (принадлежит vfd_comm) — только упомянуть в шапке-комментарии как reserved.
- Новые top-level секции: `constants:` (PROTO_VER=0x0200, SC_BASE, SC_STRIDE=8, SC_CAP=96 — пометить «до GATE-1», WRITE_CHUNK=30, READ_MAX=125), `opcodes:` (11 опкодов из plan.md с argc и раскладкой аргументов), `errno:` (15 кодов с русскими описаниями), `params:` (полный словарь v1.0 из plan.md: id/имя/label/unit/scale/signed/min/max/default/group; workspace-дефолты — консервативная рамка по фактике v1: X 100..600 мм, Y −600..0, Z −150..0, RZ −180..180 — в комментарии «placeholder, подтвердить по паспорту SCARA на Ф7»), `scenario:` (kinds LINE/LINE_PASS/JOINT, actions NONE/DO_ON/DO_OFF/DELAY_MS/SPEED_PCT/ACCEL_MMSS, раскладка записи +0..+7).
- Шапка-комментарий: назначение, word_order, инварианты (маркер последним, DW-чётность, probe до записей), ссылка на plan.md.
**Приёмка:** `python -c "import yaml; yaml.safe_load(open('Services/robot_comm/protocols/delta_v2.yaml'))"` ок; поштучная самосверка с plan.md (адреса, id, argc — списком в отчёте агента); `load_protocol` парсит секцию registers (если давится новыми top-level секциями — зафиксировать факт в отчёте, НЕ чинить: решение в T1.1 — риск №4 плана).

### T0.2 — ADR (Sonnet, Layer: docs)

**Файл (править):** `Services/robot_comm/DECISIONS.md` (прочитать формат существующих ADR-RC-001..008; нумерация с **009** — 006..008 заняты).
**Сделать:** четыре ADR по plan.md: RC-009 «Единый mailbox + выводимая активность», RC-010 «YAML→кодоген (гибрид)», RC-011 «Сценарии вместо RETURN/TOOLCHANGE; tool-state на ПК», RC-012 «Watchdog + seq-модель ошибок вместо busy-флагов». Каждый: Контекст/Решение/Последствия/Отвергнутые альтернативы (из plan.md: SET_MODE-регистр, чисто-рантайм YAML, 4-рег stride, busy-флаги).
Затем `python -m scripts.sync` (пересборка сводных разделов) и `python scripts/validate.py`.
**Приёмка:** validate зелёный; в глобальном индексе `multiprocess_framework/DECISIONS.md` появились ссылки.

### T1.1 — Кодоген (Sonnet, Layer: services)

**Файлы (создать):** `Services/robot_comm/codegen.py`, `Services/robot_comm/core/protocol_v2.py` (генерат, коммитится), `Services/robot_comm/tests/test_codegen_v2.py`.
**Сделать:**
- `codegen.py`: чтение YAML → (а) `core/protocol_v2.py`: таблицы-константы `REG` (имя→адрес), `OP`, `ERR`, `PARAMS` (id→мета dataclass/dict), `CONSTANTS`, `SCENARIO`; шапка «AUTOGENERATED из delta_v2.yaml — не править руками»; (б) функция `lua_block() -> str`: Lua-таблицы `REG={...} OP={...} ERR={...} PDEF={...}` (И3) между маркерами `-- ===== BEGIN GENERATED (delta_v2.yaml <sha256:8>) =====` / `-- ===== END GENERATED =====`. CLI: `python -m Services.robot_comm.codegen [--check]`.
- Если T0.1 зафиксировал, что `load_protocol` давится новыми секциями — вынести контракт в `delta_v2.contract.yaml` рядом (registers остаются в `delta_v2.yaml`), codegen читает оба; иначе один файл.
- `test_codegen_v2.py`: freshness (регенерация == закоммиченному `protocol_v2.py` байт-в-байт); детерминизм (два прогона идентичны).
**Приёмка:** pytest тестов кодогена зелёный; `--check` возвращает 0 на чистом дереве.

### T1.2 — Схемные инварианты (Sonnet, Layer: tests)

**Файл (создать):** `Services/robot_comm/tests/test_protocol_v2_yaml.py`.
**Проверки (каждая — отдельный тест):** непересечение всех v2-блоков между собой и с замороженным VFD 0x1200..0x121F; все DW на чётных адресах (CMD_ARG-раскладка CVT_JOB, TLM_ENC); никакая одиночная запись клиента не превышает 30 рег, чтение — 125 рег (PMIR по max id, TLM целиком); SC_BASE+SC_CAP×8 ≤ потолок из `constants:`; param id уникальны и стабильны (snapshot-файл `tests/param_ids.snapshot` — изменение id ломает тест, добавление нового — нет); у каждого opcode argc ≤ 12; errno уникальны.
**Приёмка:** pytest зелёный; умышленная порча адреса в копии YAML ловится (показать в отчёте).

### T1.3 — Сборщик прошивки (Sonnet, Layer: mixed)

**Файлы (создать):** `Services/robot_comm/build_fw.py`, `Services/robot_comm/tests/test_build_fw.py`, заглушки `robot/v2/src/00_header.lua` и `robot/v2/src/10_generated.lua` (пустые секции-скелеты для теста сборки).
**Сделать:**
- Сборка: файлы `robot/v2/src/NN_*.lua` в лексикографическом порядке → `robot/v2/main_v2.lua`; секция `10_generated.lua` перезаписывается выводом `codegen.lua_block()` при каждой сборке; в шапку артефакта — FW_BUILD (u16 = CRC16 от конкатенации исходников — детерминированно, без времени) + список секций.
- Линты (fail сборки): дублирующиеся присваивания глобалов между секциями (regex по `^[A-Za-z_][A-Za-z0-9_]* *=` вне `local`); в файле `80_mirror.lua` запрещены `while`, `WAIT(`, `DELAY(` (И4); наличие обязательных секций 00/10/80/90/99; артефакт отличается от пересборки → подсказка «запусти build_fw».
- CLI: `python -m Services.robot_comm.build_fw [--check]`.
- `test_build_fw.py`: freshness артефакта; линт ловит подсаженный `DELAY(` в 80_mirror (фикстурой во временной копии).
**Приёмка:** pytest зелёный; `--check` 0 на чистом дереве.

### T1.4 — Проба потолка адресов (Sonnet, Layer: scripts; исполнение — владелец)

**Файл (создать):** `scripts/probe_modbus_ceiling.py`.
**Сделать:** standalone-скрипт (pymodbus, host/port/unit из argv, дефолты из `RobotConfig`): БЕЗОПАСНАЯ проба только НЕиспользуемых v1-адресов — чтение FC3 и запись-восстановление FC6/FC16 по сетке 0x1560, 0x1600, 0x16FF, 0x1700, 0x17FF, 0x1800; для каждого адреса печать OK/exception; итоговая строка «потолок ≥ 0xXXXX». Жёсткий запрет трогать 0x1100..0x154B (рабочее пространство v1!). Инструкция запуска в докстроке (робот включён, программа v1 может работать в idle).
**GATE-1 (владелец):** запустить у железа, результат (потолок) сообщить → правка `constants:` в YAML (SC_CAP/резерв) + регенерация. До GATE-1 фазы Ф2+ не стартуют.

### T2.1 — sim v2: mailbox + параметры (Sonnet, Layer: services)

**Файлы:** создать `Services/robot_comm/server/sim_core_v2.py`, `Services/robot_comm/tests/test_sim_v2_core.py`.
**Сделать:**
- Класс `RobotSimCoreV2(regs: list[int])` по образцу интерфейса v1-`RobotSimCore` (tick(), attach к живому списку) — ВСЕ офсеты импортом из `protocol_v2.REG` (И1, ни одного литерала адреса).
- `tick()`: обнаружение `CMD_FLAG==1` → чтение SEQ/OPCODE/ARGC/ARGS → `CMD_FLAG=0` → валидация (неизвестный opcode → NAK E_BAD_OPCODE; argc мимо таблицы → E_BAD_ARGC; повторный seq — идемпотентный повтор последнего RES) → диспатч таблицей → запись RES (STATUS/ERRNO/RVALS, `RES_SEQ` последним, И5).
- Опкоды этой задачи: PING (rvals=[PROTO_VER, FW_BUILD]), CLEAR_ERR, SERVO, PARAM_SET (валидация min/max из `PARAMS` → E_RANGE/E_BAD_PARAM; write-through в PMIR), PARAM_GET. STOP — каркас (уровни принимаются, действия дополнит T2.2). Занятость: длинная команда в полёте → всем кроме STOP/PING NAK E_BUSY.
- Инициализация: PROTO_VER/FW_BUILD/PMIR-дефолты из `PARAMS`, ACTIVITY=IDLE, HB_ROBOT инкремент каждый tick.
**Тесты (минимум):** ACK/NAK-ветка на КАЖДЫЙ опкод задачи; PARAM_SET вне min/max → E_RANGE и значение НЕ изменилось; зеркало читается блоком и совпадает со словарём; повторный seq идемпотентен; E_BUSY при занятости.
**Приёмка:** pytest зелёный; в тестах есть прод-значения (P_SPD_DEFAULT=80, P_WDG_TIMEOUT_MS=1500).

### T2.2 — sim v2: движение (Sonnet, Layer: services)

**Править:** `sim_core_v2.py`, тесты там же.
**Сделать:**
- Модель позы: текущая X/Y/Z/RZ (float, мм/°), публикация в TLM каждый tick (×scale). Движение = **линейная интерполяция** к цели со скоростью `SpdL_экв × spd_pct/100` за tick (номинал в константах sim; главное — НЕ мгновенный скачок: минимум 3 тика на характерный ход 100 мм).
- PTP_MOVE/HOME/JOG_STEP: валидация цели `in_workspace` по PARAMS (NAK E_RANGE до старта), ACK сразу, ACTIVITY=PTP/JOG, MOVING=1; по прибытии MOVING=0, ACTIVITY=IDLE, `TLM_DONE_SEQ=seq`. JOG_STEP — цель относительно текущей позы, spd_pct=0 → P_SPD_JOG.
- STOP-уровни: 1 SOFT — доехать текущую цель и стоп; 2 HARD — замереть на месте, прерванная команда → `TLM_ERR_SEQ=seq`, ERRNO_LAST=E_ABORTED; 3 HARD+HOME — замереть, затем интерполяция в P_HOME; 4 ESTOP — замереть, SERVO=0, VFD-стоп (флаг в sim-состоянии для теста). E_NO_SERVO при движении с выключенным серво.
**Тесты:** интерполяция видна (поза меняется ≥3 тиков, монотонно к цели); done-семантика; каждый STOP-уровень; E_RANGE на цели вне workspace (прод-границы); E_NO_SERVO.

### T2.3 — sim v2: сценарии, CVT, wdg, standalone (Sonnet, Layer: services)

**Править:** `sim_core_v2.py`, `server/sim_robot.py` (добавить `--protocol v2` НЕ ломая v1-режим), тесты.
**Сделать:**
- SC_RUN: чтение `count` записей из SC-буфера, тотальная валидация ДО движения (kind/action ∈ словарю, координаты in_workspace; ошибка → NAK E_SC_RECORD, rval0=индекс; count>SC_CAP → E_SC_COUNT); исполнение по точкам с интерполяцией; ACTION после прихода в точку (DO_ON/OFF → TLM_GRIP; DELAY_MS → пауза в тиках; SPEED_PCT/ACCEL — смена скорости интерполяции); прогресс `TLM_SC_INDEX` ТОЛЬКО на точках KIND≠LINE_PASS; `TLM_SC_TOTAL/SC_ID/SC_DONE_N`; STOP посреди сценария → E_ABORTED + инвариант «DO-состояние соответствует последней исполненной точке».
- CVT_JOB: модель ленты — энкодер `TLM_ENC` тикает с настраиваемой скоростью; цель забора = pick + (enc_now − ecap)×факт; исполнение как интерполяция за движущейся целью → grip → place (из args или из PARAMS по place_mode) → home; зона P_ZONE_MIN/MAX → E_ZONE_TRIP async; MISS_COUNT.
- Watchdog: sim следит за HB_PC; «замер» дольше P_WDG_TIMEOUT_MS (в тиках через номинал tick-периода) → WDG_STATE=2, VFD-стоп, обрыв активности, async E_WDG_TIMEOUT. P_WDG_TIMEOUT_MS=0 → выключен.
- Standalone: `python -m Services.robot_comm.server --protocol v2` поднимает TCP :5021; README-раздел «dev-переключатель»: `data/devices.yaml` → host 127.0.0.1, port 5021, params.protocol v2.
**Тесты:** сценарий с DO/DELAY/SPEED-действиями и прогрессом; E_SC_RECORD с верным индексом; abort посреди; CVT-цикл с движущейся лентой (прод-факт 0.144473 мм/имп); wdg-trip (прод 1500 мс) и wdg-off; e2e через pymodbus-транспорт (порт 5021) — PING/PTP.

### T3a.1 — client_v2 ядро (Sonnet, Layer: services)

**Файлы:** создать `Services/robot_comm/core/client_v2.py`, `Services/robot_comm/tests/test_client_v2.py`.
**Сделать:**
- `RobotClientV2(device, config, clock/sleep инъекция как в v1-client)`; `probe()` — чтение PROTO_VER, ≠0x02xx → исключение `WrongFirmware` (никаких записей до probe, И-план); `cmd(opcode, args, timeout, allow_busy_retry)` — одна транзакция `[("wm", CMD_SEQ.., [seq,opcode,argc]+args), ("w", CMD_FLAG, 1)]` (маркер последним, И5), поллинг `RES_SEQ==seq` (шаги 0.01/0.05 как v1), разбор RES: NAK → typed-исключение `RobotNak(errno, name, rvals)` с русским текстом из ERR; ACK → rvals.
- `wait_done(seq, timeout)` — поллинг TLM_DONE_SEQ/ERR_SEQ (ERR → `RobotAsyncError(errno)`); `kick_heartbeat()` — инкремент HB_PC (FC6, вне mailbox); seq-генератор 1..65535 с пропуском 0.
**Тесты (против sim v2 через fake/loopback-транспорт, образец — v1 conftest):** probe на v1-пространстве (нули) → WrongFirmware; ACK-путь; NAK → исключение с errno; wait_done happy/err; heartbeat меняет HB_PC; E_BUSY-retry для не-allow_busy.

### T3a.2 — client_v2 обёртки + golden (Sonnet, Layer: services)

**Править:** `client_v2.py`; создать `tests/test_wire_golden_v2.py`.
**Сделать:** типизированные обёртки `ptp_move/home/jog_step/cvt_job/scenario_run/stop/servo/param_set/param_get/param_read_all/ping`; `upload_scenario(points)` — сериализация записей по `SCENARIO`-мете, чанки 24 рег (3 записи), затем SC_RUN; `param_read_all()` — FC3 PMIR по max id.
Golden: для каждой обёртки — плоский лог `(kind, addr, values)` записей на фейк-транспорте → снапшот-файл; шапка снапшота: «self-referential эталон v2 (НЕ hardware-validated); класс гарантии восстанавливается на Ф7».
**Тесты:** golden совпадает; upload 96 точек = ожидаемое число транзакций; изменение YAML-адреса ломает golden (продемонстрировать в отчёте на копии).

### T3b.1 — scenarios/model (Sonnet, Layer: services)

**Файлы:** создать пакет `Services/robot_comm/scenarios/{__init__,model}.py`, `tests/test_scenarios.py`.
**Сделать:** `ScPoint` (x,y,z,rz,kind,action,aparam; Pydantic внутри, `to_regs()/from_regs()` по `SCENARIO`-мете), `Scenario` (points, sc_id, index_map: список «индекс точки → индекс исходной точки штриха/шага», валидации: ёмкость ≤SC_CAP, все точки in_workspace(PARAMS), последняя точка не LINE_PASS, DELAY/DO aparam в диапазонах). Разбиение `split_passes(scenario, cap)` — только по границам EXACT-точек.
**Тесты:** round-trip to_regs/from_regs (property по сетке значений включая отрицательные s16); валидации; split только по EXACT; index_map сохраняет соответствие при split.

### T3b.2 — scenarios/draw.py (OPUS, Layer: services)

**Файл:** создать `Services/robot_comm/scenarios/draw.py`, тесты в `test_scenarios.py`.
**Контекст-семантика (перенести ТОЧНО, источник — v1 Lua `robot/main_actual.lua:521-624` и ревью):** вход — штрихи `[[(x,y),...], ...]` + параметры рисования (pen_down_z, pen_up_z, draw_spd_pct, travel_spd_pct, accel, финальный подъём DRAW_LIFT_MM=10, home-флаг). Выход — `Scenario`.
**Правила генерации:**
1. Начало штриха: подъём вертикально в ТЕКУЩЕМ XY до pen_up (EXACT) → переезд на высоте к старту штриха (EXACT, SPEED_PCT=travel) → опускание вертикально до pen_down (EXACT, SPEED_PCT=draw). Первая точка сценария — без «подъёма из ниоткуда» (робот стартует сверху).
2. Внутри штриха: LINE_PASS точки на pen_down (draw-скорость).
3. **Конец штриха — EXACT** (фикс v1-бага «срез конца штриха на overlap»).
4. Финал: подъём в текущем XY до pen_up+DRAW_LIFT (EXACT); при home-флаге — JOINT-точка в P_HOME.
5. ACCEL-действие первой точкой, если accel задан.
6. index_map: каждая точка сценария → индекс исходной точки штриха (служебные точки → индекс ближайшей исходной).
**Тесты:** golden-геометрия на фикстуре «две буквы Л+И» (снапшот списка точек); property: нет LINE_PASS между разными штрихами; все Z ∈ {pen_down, pen_up, pen_up+lift}; конец каждого штриха EXACT; скорости чередуются travel/draw корректно; split на cap=41 (пессимизм GATE-1) не рвёт штрихи в PASS-середине.

### T3b.3 — return/toolchange + e2e (Sonnet, Layer: services)

**Файлы:** создать `scenarios/return_gen.py`, `scenarios/toolchange.py`, `tests/test_sim_e2e_v2.py`.
**Сделать:**
- `return_gen(slot_xyz, lift_mm=20, push_mm=100, grip_ms)` — последовательность v1 RETURN (подвод сверху EXACT → опуск → DO_ON+DELAY → подъём → сдвиг X → опуск → DO_OFF+DELAY → JOINT home), все точки EXACT.
- `toolchange(current, target, points: teach-словарь из devices.yaml {tN_over/sock/exit}, transit)` — маршрут v1 (снятие exit→sock(+DELAY)→over[→transit], надевание [transit→]over→sock(+DELAY)→exit); при отсутствии teach-точек — понятная ошибка «обучите точки в панели». Состояние инструмента НЕ здесь (оно на ПК-стороне, драйвер T5.1).
- e2e (client_v2 ↔ sim v2): draw двумя проходами (cap искусственно 8) с проверкой SC_DONE_N/прогресса; return полный с проверкой TLM_GRIP-хронологии; toolchange 1→2; CVT job на движущейся ленте; STOP(2) посреди сценария; wdg-trip.
**Приёмка:** e2e зелёные; `python scripts/validate.py` зелёный.

### T4.1–T4.4 — Прошивка (ОДИН Opus-агент, отдельный worktree, Layer: mixed)

**Настольная книга:** [firmware-architecture.md](firmware-architecture.md) — карта секций с контрактами экспорта, потоковая модель Motion/Mirror, state-машина ACTIVITY, дисциплины ошибок и скорости, ловушки DRAS, таблица закрытия находок. Отступление от неё — только с письменным обоснованием в отчёте задачи.

**Создать:** `robot/v2/src/*.lua` по карте секций, `robot/v2/main_v2.lua` (сборкой), `.luacheckrc` в `robot/v2/`.
**Карта секций (= файлы):**
```
00_header.lua   шапка, версия, назначение
10_generated.lua  (генерат codegen — руками не трогать)
20_util.lua     iround/clamp/s16-конверсии; rdW/rdDW/wrW (nil-safe, И6)
30_vfd.lua      мост RS-485 + legacy-mailbox 0x1200 (перенос ДОСЛОВНО из main_actual.lua:156-341,343-386 — менять только имена под rdW/wrW)
40_params.lua   P{} из PDEF; param_set(id,v)→валидация+зеркало; полный сброс зеркала на boot
50_safety.lua   in_workspace(x,y,z); pending_stop-защёлка; wdg_check (Systime если есть; иначе счётчик итераций ×2 — явный комментарий «bring-up режим»)
60_mailbox.lua  OPS-таблица {argc,allow_busy,fn}; mb_poll(); mb_poll_light(); res_write() (RES_SEQ последним, И5); pcall вокруг fn → E_INTERNAL
70_motion.lua   motion_prologue(spd)/motion_epilogue() (Override/AccL восстановление на ВСЕХ выходах); guarded_move(движение+проверка pending_stop ПОСЛЕ КАЖДОГО примитива)
71_exec.lua     exec_ptp, exec_jog (цель от текущей позы), exec_home
73_cvt.lua      exec_cvt (перенос трекинг-механики v1 run_job: VelIn/VelOut, зона, miss; place из args/params; ВСЕ координаты через in_workspace; Override из P_SPD_DEFAULT в prologue — фикс находки 1)
74_scenario.lua exec_scenario: пред-чтение чанками (≤30 рег) в таблицы ДО движения; тотальная валидация (E_SC_RECORD+индекс, E_BUF_SHORT при коротком чтении — НЕ молчаливое усечение); цикл: KIND-диспатч движения, ACTION после прихода; прогресс только на EXACT; mb_poll_light на EXACT
80_mirror.lua   Mirror(): pcall всего тела; publish-поза (безопасно); зеркало энкодера; peek CMD (opcode==STOP → MotionStop + pending_stop, флаг НЕ трогать); zone-check при CVT. БЕЗ while/WAIT/DELAY (линт)
90_motion.lua   Motion(): while running → pcall(motion_body); recovery: epilogue+ACTIVITY=IDLE+NAK/ERR_SEQ E_INTERNAL; motion_body: wdg_check→mb_poll→VFD-mailbox→телеметрия(P_TLM_EVERY)→DELAY(0.005)
99_boot.lua     печать версии; PROTO_VER/FW_BUILD/зеркало ПЕРВЫМИ; серво; MultiTask(Motion, Mirror)
```
**Порядок работ (коммит на подзадачу):** T4.1 (00,20,40,50 + сборка) → T4.2 (60) → T4.3 (70,71,73,74) → T4.4 (30,80,90,99 + полный luacheck).
**Жёсткие требования:** телеметрия и VFD обслуживаются при ЛЮБОЙ активности (находка 7); никакого чтения Modbus в циклах движения кроме mb_poll_light на EXACT (сохранение PASS-блендинга); WritePoint скретч-точек — всегда ВСЕ координаты X/Y/Z/R (находка 3); состояние инструмента в прошивке НЕ хранится (находка 4); стейл-комментарии запрещены — комментарий только про инвариант.
**`.luacheckrc`:** глобалы DRAS (MovL/MovP/MCircle/WritePoint/SetGlobalPoint/ReadModbus/WriteModbus/MultiReadModbus/MultiWriteModbus/DELAY/Override/SpdL/SpdJ/AccL/DecL/AccJ/DecJ/Accur/DO/RobotX/Y/Z/RZ/RobotHand/RobotServoOn/Off/MotionStop/MultiTask/CVT_*/SCM_*/PassMode/SetOverlapDistance/PASS/SPD/Systime — сверить фактический список по v1-файлу) + разрешённые собственные глобалы (Motion, Mirror, REG/OP/ERR/PDEF, P).
**Приёмка T4.4:** `python -m Services.robot_comm.build_fw --check` 0; `luacheck robot/v2/src` 0 warnings; самоотчёт-таблица «находка ревью → файл/функция закрытия».

### T4.5 — README прошивки (Sonnet, Layer: docs)

`robot/v2/README.md`: карта секций; сборка/заливка (DRAStudio: какой файл, как); переключение v1↔v2 (какой Lua + `devices.yaml params.protocol`); таблица 10 находок → закрытие; bring-up чек-лист Ф7 ДОСЛОВНО из plan.md Ф7-строки, разбитый на шаги с ожидаемыми результатами.

### T4.6 — Контракт-тесты находок (Sonnet, Layer: tests)

**Файл:** `Services/robot_comm/tests/test_findings_contract_v2.py`. Десять именованных тестов `test_finding_01_override_leak` … `test_finding_10_busy_stuck` — каждый воспроизводит СЦЕНАРИЙ находки v1 против sim v2 и проверяет v2-поведение (пример: finding_01 — после сценария с SPEED_PCT=100 следующий PTP идёт на P_SPD_DEFAULT: в sim скорость интерполяции вернулась; finding_10 — уронить обработчик (тестовый opcode-хук/monkeypatch) → RES с E_INTERNAL всё равно записан, ACTIVITY=IDLE). Докстрока каждого теста — цитата находки. При наличии T4.7 — второй прогон против прошивки.

### T4.7 — (stretch) lupa-харнесс (Opus, Layer: tests)

`robot/v2/harness/`: lupa (LuaJIT) + моки DRAS-глобалов (движение = запись в лог + телепорт позы; Modbus = общий список регистров с sim-тестами); прогон СОБРАННОГО `main_v2.lua`; дифф «лог операций прошивки vs лог sim v2» на последовательностях из test_sim_e2e_v2. Вне критического пути: не блокирует REVIEW-4. dev-зависимость lupa — в `[project.optional-dependencies]`.

### T5.1 — Драйвер: дуальный диспатч (OPUS, Layer: services)

**Править:** `Services/device_hub/drivers/robot_driver.py` (+тесты драйвера).
**Сделать:**
- Слой протокола: `params.protocol: v1|v2` (дефолт v1!) → фабрика клиента (v1 `RobotClient` / v2 `RobotClientV2` + probe при connect; probe-fail → статус-ошибка «в контроллере v1-прошивка», не крэш).
- Таблица соответствий op→реализация: v1-ветки НЕ трогать (регресс-инвариант); v2-ветки: `jog→JOG_STEP`, `abort/stop→STOP(level)`, `servo`, `telemetry→TLM-блок`, `set_robot_config→циклы PARAM_SET`, `get_robot_config→param_read_all`, `send_test_job→CVT_JOB`, `draw_polyline/circle/square→scenarios.draw+scenario_run` (круг/квадрат — полилин步 аппроксимацией на ПК или отклонить с понятным сообщением — решить и задокументировать), `draw_set_pen/speed/travel/accel/overlap→запись в PC-настройки генератора (devices.yaml params.draw)`, новые: `ptp`, `scenario_run`, `param_get_all`, `teach_capture` (поза из TLM → возврат dict), `return_job→return_gen`, `toolchange→toolchange-генератор + tool-state в devices.yaml (чтение/запись через RegistryStore; abort посреди → state="unknown" + требование подтверждения)`.
- push-параметров-on-connect (v2): `devices.yaml params.robot_params` → PARAM_SET цикл → сверка по зеркалу → лог расхождений; heartbeat: `kick_heartbeat()` в tick-воркере с периодом ≤ P_WDG_TIMEOUT/4.
**Приёмка:** существующие тесты драйвера (v1) зелёные БЕЗ правок; новые тесты v2-веток против sim v2.

### T5.2 — device_hub + robot_draw (Sonnet, Layer: plugins)

`Plugins/hub/device_hub/plugin.py`: команды `robot_ptp`, `robot_scenario_run`, `robot_param_get_all`, `robot_teach_capture` (+алиасы старых имён без изменений сигнатур). `Plugins/io/robot_draw/plugin.py`: при protocol=v2 форвардер шлёт штрихи как есть (генерация сценария в драйвере) — интерфейс плагина не меняется, только маршрут. Тесты плагина.

### T5.3 — Тесты драйвера (Sonnet, Layer: tests)

Матрица: v1-путь регресс (все старые op без изменений поведения — против sim v1); v2-путь против sim v2 (каждый op из T5.1-таблицы: happy + NAK-прокидка); push-on-connect (расхождение зеркала логируется); heartbeat-период (прод 1500/4 мс); probe-fail сценарий. Прод-значения обязательны минимум в одном тесте каждого блока.

### T6.1 — Панель robot_settings (Sonnet, Layer: prototype)

**Создать:** `multiprocess_prototype/frontend/widgets/tabs/services/robot_settings/{__init__,widget,presenter,controller,section}.py` по образцу соседнего `robot/` (тот же стиль MVP: widget без логики, presenter → CommandSender("devices"), controller — подписки).
**Сделать:** группы формы — из YAML `params:` `group:` (мета через `load_protocol`/`protocol_v2.PARAMS`): спинбоксы с unit/min/max/step, кнопки «Прочитать с робота» (param_get_all), «Записать» (PARAM_SET по изменённым, NAK → красная подсветка поля + текст errno по-русски), «Сбросить к дефолтам YAML». Секция регистрируется в `_sections.py` рядом с «Робот Delta».
**Приёмка:** presenter-тесты offscreen (образец `test_robot_presenter.py`): маппинг полей→команд, NAK-обработка.

### T6.2 — Ревизия draw-call-site (Sonnet, Layer: prototype)

Перед стартом — свежий grep: `draw_circle|draw_square|draw_set_speed|draw_set_pen|draw_set_overlap|draw_set_travel|draw_set_accel` по `multiprocess_prototype/frontend/` (ориентир: 33 вхождения). Для каждого: при protocol=v2 контрол работает через новые PC-side настройки/генерацию (T5.1) или скрывается с тултипом «в v2 — панель настроек». Изменения таблицей в отчёте (файл:строка → решение). Существующее поведение при v1 — без изменений.

### T6.3 — Teach + диалог инструмента (Sonnet, Layer: prototype)

Расширить СУЩЕСТВУЮЩИЙ `services/robot/calibration/` (НЕ создавать параллельный): вкладка/секция «Точки робота» — список (HOME, PLACE, PICK-Z, слот RETURN, t1/t2 over/sock/exit) с текущими значениями из devices.yaml; кнопки «Подъехать» (PTP на pen_up-высоте), «Захватить текущую позу» (`robot_teach_capture` → запись в devices.yaml через RegistryStore + пуш параметров-точек в робота). Диалог при неизвестном tool-state на connect: «Какой инструмент установлен?» (0/1/2) — конвенция кнопок платформы: Сохранить(default)/Не сохранять/Отмена → здесь: подтверждение выбора, Отмена = робот блокирован на toolchange до подтверждения.
**Приёмка:** тесты presenter/controller offscreen; teach-значение реально в devices.yaml (tmp-фикстура).

### T6.4 — GUI-тесты сводно (Sonnet, Layer: tests)

Добить пробелы покрытия T6.1–T6.3 (если остались), прогнать весь `pytest multiprocess_prototype/frontend/widgets/tabs/services/ -q` offscreen; `python scripts/validate.py`.

### Ф7 — Железо (владелец + live-агент, вне брифов)

По чек-листу `robot/v2/README.md` (T4.5). Итоги каждого пункта — в README (факт/тюнинг); финальные дефолты → YAML → регенерация → коммит `docs(robot): Ф7 bring-up результаты`.

---

## 4. Брифы ревью

- **REVIEW-4 (прошивка), REVIEW-5 (драйвер):** формальный `/code-review` (полный). Финдеры — Sonnet (углы: корректность/конкурентность Motion-Mirror/выход-пути-epilogue/соответствие YAML), верификация — Opus. Обязательная сверка: таблица находок T4.4, инварианты И1–И8.
- **REVIEW-6 (GUI):** лёгкое групповое (один Sonnet-проход: сигналы/слоты, offscreen-тесты, конвенция диалогов).
- Merge в `main` (M1/M2/M3) — только после соответствующего ревью, отдельным решением владельца.
