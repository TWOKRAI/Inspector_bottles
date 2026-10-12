"""Ядро симулятора робота протокола v2 (T2.1+T2.2, plans/robot-protocol-v2).

Эмулирует Motion-цикл прошивки Delta v2 НАД массивом регистров:

- mailbox (``CMD_*``/``RES_*``) — приём одной команды за тик, ACK/NAK, повтор
  последнего ``seq`` не исполняется заново (идемпотентность, включая повтор
  после рестарта программы — последний ответ восстанавливается из регистров
  при загрузке);
- зеркало параметров (``PMIR`` + ``PMIR_MAGIC``/``PMIR_CRC``/``PMIR_DICT``) —
  валидируется при загрузке (magic + fingerprint словаря + CRC16/MODBUS),
  битые слоты откатываются к дефолту поштучно;
- плоскость ``STOP_REQ`` — действует только на ИЗМЕНЕНИЕ значения, HARD/HALT
  обрывают активную команду, HALT дополнительно гасит серво и шлёт стоп ПЧ
  (``vfd_stop_requests`` — счётчик-заглушка до моста ПЧ, T2.3).

Реализовано в T2.1: ``PING``, ``CLEAR_ERR``, ``SERVO``, ``DO_SET``,
``PARAM_SET``/``PARAM_GET``/``PARAM_APPLY``.

Реализовано в T2.2 (protocol-spec §3.4, §4, §5, §6, §7.3, §8; params.md
§11.3): настоящая интерполяция ``PTP_MOVE``/``HOME``/``JOG_STEP`` (линейно в
Cartesian для ``LINE``/``JOG_STEP``; ``JOINT``/``HOME`` — по суставам модели,
см. T2.J ниже), ``JOG_CONT`` с поводком (``JOG_LEASE``) и остановкой на краю
зоны, проверка рабочей зоны через уже принятую ``programs/geometry.py``
(``Workspace``/``check_point``/``check_segment`` — переиспользуются, не
копируются), ``E_NO_SERVO`` для всех опкодов движения, плоскость стопа с
уровнями SOFT (pending для хода, abort now для jog) / HARD / HALT,
``inject_motion_fault()`` (``FAULT``, ``TLM_ACTIVITY=5``) с gating (только
``PING``/``CLEAR_ERR``/``PARAM_GET``/``PARAM_SET``/``SERVO`` разрешены).
Упрощение симулятора: замедление стопа HARD (``P_DEC_STOP``) не моделируется —
поза замирает на тике обработки.

Отложено: TCP-сервер ``--protocol v2`` и плагин хоста (T2.4). v1-симулятор
(``sim_core.py``) не используется и не импортируется — новый протокол живёт в
отдельном адресном пространстве.

Реализовано в T2.3, часть B (protocol-spec §5 CVT_JOB, §9, §10; ADR-RC-016/017):

- Конструктор: ``belt`` (``BeltDrive``; ``None`` -> скорость v1 ``enc_rate=7``),
  ``on_event(text)``, ``on_job_done(event)``. Публичные имена для хоста:
  ``belt``, ``belt_mm_s``, ``encoder`` (= ``TLM_ENC``, растёт от
  ``belt.advance(dt)`` каждый тик), ``command_vfd(run=, freq_hz=, reverse=)``
  (семантика v1: поля mailbox, ``VFD_FLAG`` последним, применение на тике),
  ``vfd_fault_code``, ``VFD_CMD_ADDR``; хуки ``inject_vfd_link_fault()``/
  ``clear_vfd_link_fault()``.
- Разделение (ADR-RC-017): ядро — сторона ПРОШИВКИ моста ПЧ (ретрансляция
  mailbox ``0x1200..`` в ``belt`` и зеркало статуса ``0x1210..``); адреса и
  масштабы — только из ``Services/vfd_comm/core/registers.py``; физика ПЧ и
  ленты — только в инжектируемом ``belt``. Эмуляции сервоприводов в ядре нет.
- ``CVT_JOB``: ``TLM_ACTIVITY=3``. Следимая точка pick = ``(pick_x, pick_y)`` +
  ``(TLM_ENC − ecap) × P_BELT_FACTOR·1e-5`` вдоль оси ``P_BELT_DIR``. Подход —
  JOINT к следимой точке на высоте pick (цель пересчитывается каждый тик),
  захват мгновенный, JOINT в укладку, ``DONE_SEQ``, затем ``on_job_done``
  (``index`` — счёт принятых CVT_JOB с 1, ``x_mm``/``y_mm`` — pick из
  аргументов, ``ecap``, ``t`` — время sim, сумма ``dt_s``). Промах — следимая
  точка вне кольца ``P_ZONE_MIN..P_ZONE_MAX`` на любом тике подхода (включая
  тик приёма) -> async ``E_ZONE_TRIP``, ``TLM_MISS_COUNT + 1``, DONE не пишется.
- Сторожевой таймер и мост ПЧ обслуживаются КАЖДЫЙ тик, и внутри сценария, и во
  время хода (расхождение с §7.2 п.4, §9.3, §10.4 — ADR-RC-016). HALT и сторож
  останавливают ленту ``belt.command(run=False)``.

Формат строк ``on_event`` (разбирает ``sim_journal.SimJournal.on_event``)::

    [v2] CMD seq=<seq> op=<ИМЯ>            принятая команда (ACK, не повтор seq)
    [v2] DONE seq=<seq> op=<ИМЯ>           штатное завершение хода/CVT/сценария
    [v2] ERR seq=<seq> errno=<n> <E_ИМЯ>   async-ошибка (ERR_EVT + 1); seq=0 — вне команды
    [v2] SC start id=<id> count=<n>        начало сценария
    [v2] SC end id=<id> done_n=<n>         конец сценария (успех или обрыв)
    [v2] CVT grip seq=<seq> x=<мм> y=<мм>  захват в следимой точке
    [v2] CVT miss seq=<seq> x=<мм> y=<мм>  промах (перед строкой ERR E_ZONE_TRIP)

Реализовано в T2.3, часть A (protocol-spec §7, §3.4 ``TLM_SC_*``/``TLM_SPD_PCT``):

- ``SC_RUN(count, sc_id, offset)``: ``count`` вне ``1..SC_CAP`` или
  ``offset+count > SC_CAP`` -> NAK ``E_SC_COUNT``; затем ``E_NO_SERVO``; затем
  ВЕСЬ срез проверяется до движения (KIND, ACTION, APARAM, точка в зоне, отрезок
  LINE/LINE_PASS — первый от текущей позы, последняя запись не LINE_PASS, рука
  §7.3, пределы суставов JOINT — тем же путём, что ``_check_motion``,
  ``_check_target``); первая ошибка -> NAK ``E_SC_RECORD``, rval0 = индекс
  внутри среза (0-based от ``offset``), rval1 = причина ``R_*``. NAK не
  оставляет следов (поза, DO, ``TLM_SC_*`` не пишутся).
- Исполнение: ``TLM_ACTIVITY=4``, ход каждой записи — те же
  ``_start_move``/``_progress_move``, что у одиночного хода. Действие записи —
  после прихода. ``TLM_SC_INDEX`` (1-based номер в срезе) пишется на тике
  прихода в EXACT-точку (KIND != LINE_PASS), на LINE_PASS не меняется.
- Гейт §7.2 п.4: внутри сценария mailbox и SOFT-стоп обслуживаются ТОЛЬКО на
  EXACT-точке, на тике завершения записи (приход + действие; у ``DELAY_MS`` —
  тик окончания паузы); следующий отрезок стартует в том же тике. HARD/HALT —
  сразу, каждый тик. ⚑ Расхождение с §4.3 (решение ведущего, DECISIONS
  ADR-RC-015): ОДИНОЧНЫЕ ходы PTP/HOME/JOG по-прежнему обслуживают mailbox
  каждый тик (тесты T2.1/T2.2: ``live``-команды во время хода). Сторожевой
  таймер и мост ПЧ (часть B) в сценарии обслуживаются каждый тик, не только
  на EXACT.
- ``DELAY_MS`` — миллисекунды ВРЕМЕНИ SIM: копится сумма ``dt_s`` из
  ``tick``, стенные часы не читаются; на тике прихода пауза не завершается.
  ``DELAY_MS=0`` — без паузы.
- ``SPEED_PCT``/``ACCEL``/``ACCUR`` живут в состоянии сценария до его конца
  (``ACCEL``/``ACCUR`` только хранятся — разгон и точность sim не моделирует);
  на любом выходе действуют снова ``P_SPD_DEFAULT``/``P_ACC_L``/
  ``P_ACCUR_DEFAULT`` (``_values`` сценарий не трогает). Стоп DO не трогает;
  действие записи, до которой не дошли, не исполняется.
- Итог успеха: ``TLM_SC_DONE_N=count``, ``TLM_SC_TOTAL``, ``TLM_SC_ID``, затем
  ``DONE_SEQ`` последним (И5). Стоп/авария посреди -> событие ``E_ABORTED``
  (``_abort``), ``TLM_SC_DONE_N`` = число завершённых записей. SOFT, ждавший
  EXACT, на последней точке тоже даёт ``E_ABORTED``, не DONE — как у
  одиночного хода T2.2.
- Промежуточные точки (и LINE_PASS) sim проходит ТОЧНО (поза равна точке на
  тике прихода) — свойство sim, не прошивки: настоящий контроллер сглаживает
  LINE_PASS (допущение A5 тестера, DECISIONS ADR-RC-015).
- ``TLM_SPD_PCT`` — текущий Override, %: на старте хода — ``spd_pct`` команды
  (0 -> ``P_SPD_DEFAULT``; для ``JOG_STEP`` 0 -> ``P_SPD_JOG``), в сценарии —
  ``SPEED_PCT`` сценария, в IDLE — ``P_SPD_DEFAULT``. ``JOG_CONT`` его не
  меняет (скорость там в мм/с, не в %).

Реализовано в T2.K: проверка зоны идёт через ``self.model`` (``RobotModel``,
`kinematics.py`, по умолчанию ``ScaraModel``) — не напрямую через
``geometry.check_point``/``check_segment``, чтобы кинематика (FK/IK, точки
звеньев) и делегирование в зону не требовали правок ядра при смене типа
робота. Шов ýже, чем «смена типа не требует правок ядра» (ревью T2.K,
находка 6): набор параметров зоны (``geometry.Workspace`` из ``_WS_PARAM_NAMES``)
и проверка ``R_HAND`` (``TLM_HAND != P_HAND``, ``_check_motion``/``_op_jog_cont``)
специфичны прошивке SCARA/Delta v2 и меняются вместе с протоколом для другого
типа робота — ядро их не выносит в модель.

Реализовано в T2.J: ``PTP_MOVE JOINT`` и ``HOME`` интерполируются по суставам
модели, а не по прямой в Cartesian — прямая может срезать угол через запретный
сектор ``P_WS_ANG_*``, которого у настоящей руки нет (репродукция бага —
отчёт тестера T2.J: старт/цель по разные стороны сектора, прямая хорда его
пересекает, суставный путь — нет). Фолбэк на прямую в Cartesian — ДВА
независимых случая: (1) если ``ik`` вернул ``None`` для старта или цели (точка
вне досягаемости модели) — ход ЦЕЛИКОМ остаётся на прежней прямой; (2) если
``fk`` вернул ``None`` ПОСРЕДИ пути (суставы, полученные интерполяцией
ДОСТИЖИМЫХ концов, сами оказались недостижимы для модели между ними) — на
декартов шаг падает только ЭТОТ тик, не весь ход (не пересчитывает путь
заранее). **Промежуточные точки суставного пути НЕ проверяются на попадание в
зону** — и прошивка, и симулятор проверяют только цель хода при приёме
команды (``_check_motion``). Сектор избегается не потому, что суставный путь
"физически повторяет траекторию настоящей руки" (опровергнуто ревью T2.J2:
модель БЕЗ пределов суставов проходит через сектор — инъекция ведущего дала
угол TCP до ±170°, 392 случайных хода без нарушения были на модели С пределами)
— и не механизмом вообще: что суставный путь в сектор не заходит — НАБЛЮДЕНИЕ,
не гарантия. Замер ревью T2.J2 (итерация 2): 0 из 392 случайных ходов на модели
С пределами суставов (1 пограничный угол −165.0 на 32k пар), но пределы сами
сектор не исключают — `J1=−132, J2=−100` внутри пределов даёт угол TCP −176.3°.
Без пределов (модель без `joint_limits`) сектор не защищён даже наблюдением. ``LINE`` и ``JOG_STEP``/``JOG_CONT``
остаются прямой в Cartesian без изменений.

Реализовано в T2.J2 (эскалация ревью T2.J к cto, см. `docs/reviews/2026-09-27_robot-v2-task-T2.J-cto.md`,
«Решения» и «Свойства приёмки T2.J2»): суставы — состояние симулятора, не
пересчёт `ik(позы, TLM_HAND)` по требованию:

- ``self._joints`` заводится при (пере)загрузке позы (``_boot``/``attach``, т.е.
  и рестарт с ``regs=old.regs``) через ``_set_pose_and_joints`` — единственное
  место, которое пишет позу + `_joints` + `TLM_HAND` вместе. `TLM_HAND` следует
  знаку `J2` состояния (`J2<0` -> 1, `J2>0` -> 0, `J2==0` — не меняется) —
  ⚑ GATE-1, правило SCARA-специфичное (6-осевая рука потребует метод модели,
  не заводится здесь заранее). ``joints()`` теперь читает ``self._joints``, а
  не пересчитывает — `TLM_HAND` после ЛЮБОГО обрыва (не только DONE) отражает
  физическое состояние руки, чиня устаревший `TLM_HAND = P_HAND` только на
  DONE (находка ревью T2.J №3).
- **Одна правда TLM_RZ = fk(_joints)[3] = J1+J2+J4** (вердикт cto по эскалации
  ревью T2.J2, `docs/reviews/2026-09-27_robot-v2-task-T2.J2-cto.md`): правило
  «J4 — ближайший оборот» ОТОЗВАНО — несовместимо с «TLM_RZ = цель дословно»
  (давало скачок TLM_RZ на 717.6°/тик и `fk(joints)[3] != TLM_RZ` после DONE).
  Приём JOINT/HOME: ``j_end = ik(target, P_HAND)``; J4 — СЫРОЙ (`rz - J1 - J2`,
  без перемотки ±360) везде, включая `_continuity_joints` (LINE/JOG). Если
  `j_end` не `None` — ВСЕ суставы (включая J4 сырой) проверяются одним циклом
  на `model.joint_limits`; любой вне предела — `NAK E_RANGE [R_OUT_OF_ZONE]`
  В ОДНОМ месте (⚑ GATE-1 JRC: реальный оборот сустава контроллер хранит
  отдельно от RZ — сырое правило не проверено на прошивке). Фолбэк `ik -> None`
  (недосягаемость модели по радиусу) остаётся ACK + декартов путь — предел
  сустава НЕ путается с этим фолбэком (`j_end is not None` — предпосылка всей
  ветки предела). `_start_move` переиспользует уже посчитанный `j_end`, не
  пересчитывает.
- Длительность (Q3): ``duration = max(T_cart, max_j |Δj_j| / v_j)``,
  ``v_j = joint_speed_j × P_SPD_J/100 × spd_pct/100`` (``_op_ptp_move``/``_op_home``
  по-прежнему считают декартову скорость от `P_SPD_L`, независимо). Декартов пол
  T2.2 — совместимость КОНТРАКТА, не физика (мануал RL 1.1.1: `MovP` двигает все
  оси одновременно, реальный JOINT обычно быстрее LINE). Длительность выражается
  эквивалентной длиной ``path_len_eq = duration × speed``, чтобы продвижение за
  тик оставалось `min(speed*dt, MAX_STEP_MM)` тем же кодом, что и раньше.
  ЖЁСТКИЙ ПОТОЛОК (решение ведущего 2026-09-27): декартово смещение XYZ (не RZ —
  RZ = J1+J2+J4 лерпится линейно вместе с суставами и потолком не ограничен
  отдельно, но при сыром J4 без перемотки остаётся монотонным прямым лерпом
  старт->цель, см. правило одной правды выше) за один тик ограничено
  `MAX_STEP_MM` И В СУСТАВНОМ ходе, ВКЛЮЧАЯ ФИНАЛЬНЫЙ — если `fk` кандидатной
  доли тика (включая долю,
  ограниченную `path_len`) уносит TCP дальше `MAX_STEP_MM` от предыдущей позы
  (нелинейность fk у вытянутой руки), доля тика урезается (`_joint_tick_capped`,
  несколько итераций деления пополам); ревью T2.J2 нашло, что до этого исправления
  финальный тик прыгал в цель В ОБХОД потолка (шаг до 145.2мм при смене руки,
  ⚑ БЛОКЕР 1). Позу ставит РОВНО в `target`, а `_joints` — в `j_end`, ТОЛЬКО
  тик, который реально дотянул до `path_len` без урезания; иначе ход продолжается
  на следующем тике честным капнутым шагом.
- LINE/JOG: после каждой записи позы `_joints = ik(pos, TLM_HAND)` КАК ЕСТЬ,
  БЕЗ поправок J4 (та же одна правда). Пределы суставов при LINE не
  проверяются — открыто, вне охвата T2.J2 (см. отчёт).
- Промежуточные проверки зоны ПОСРЕДИ хода (клэмп у вытянутой руки при
  округлении x/y, `_clamp_pose_to_zone`; потолок шага, `cart_dist` в
  `_joint_tick_capped`) смотрят ТОЛЬКО XY (`_check_point_xy`) — вердикт cto по
  RZ: зона RZ проверяется только на КОМАНДНОЙ цели (`_check_motion`), иначе
  узкая зона RZ ложно уводила бы в клэмп посреди хода.

⚑ GATE-1 JRC (вердикт cto): правило контроллера для оборота сустава (сырой J4
как в sim, или прошивка перематывает сама) не проверено на реальной прошивке —
мануал RL не называет диапазон `RobotRZ()`.

Убрано T2.J2: устаревший `TLM_HAND = P_HAND` только на DONE (теперь TLM_HAND
следует состоянию на каждой записи позы), мёртвый ключ `"start"` в `_active`
(дублировал `"pos"` при заводе хода).
"""

from __future__ import annotations

import math
from collections.abc import Callable

# ponytail: CRC берётся из кодогена (тянет yaml); перенести в core/, если sim уедет туда, где yaml нет.
from Services.robot_comm.codegen import crc16_modbus
from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import (
    ACT,
    CONSTANTS,
    ERR,
    KIND,
    OP,
    OP_SPEC,
    REASON,
    REG,
    REG_COUNT,
    STOP_LEVEL,
)
from Services.robot_comm.kinematics import RobotModel, ScaraModel
from Services.robot_comm.programs.geometry import Workspace
from Services.robot_comm.server.belt import BeltDrive
from Services.vfd_comm.core.registers import FREQ_SCALE as VFD_FREQ_SCALE
from Services.vfd_comm.core.registers import REG_CMD_DIR as VFD_REG_CMD_DIR
from Services.vfd_comm.core.registers import REG_CMD_FREQ as VFD_REG_CMD_FREQ
from Services.vfd_comm.core.registers import REG_CMD_RESET as VFD_REG_CMD_RESET
from Services.vfd_comm.core.registers import REG_CMD_RUN as VFD_REG_CMD_RUN
from Services.vfd_comm.core.registers import REG_ST_BASE as VFD_REG_ST_BASE
from Services.vfd_comm.core.registers import REG_VFD_FLAG as VFD_REG_FLAG
from Services.vfd_comm.core.registers import STATE_FWD as VFD_STATE_FWD
from Services.vfd_comm.core.registers import STATE_REV as VFD_STATE_REV
from Services.vfd_comm.core.registers import STATE_STOP as VFD_STATE_STOP

# ACK/NAK не входят в сгенерированный контракт (protocol-spec §4) -> литералы.
ACK = 1
NAK = 2

# ponytail: коды активности локальны для sim v2 — перенести в YAML/кодоген,
# когда та же таблица понадобится прошивке (T4).
TLM_ACTIVITY_IDLE = 0
TLM_ACTIVITY_PTP = 1
TLM_ACTIVITY_JOG = 2
TLM_ACTIVITY_CVT = 3
TLM_ACTIVITY_SCENARIO = 4
TLM_ACTIVITY_FAULT = 5

#: dt по умолчанию, когда tick() вызван без аргумента (contract §"Motion model").
TICK_INTERVAL_S = 0.01
#: жёсткий потолок декартова смещения XYZ позы за один тик, мм (contract
#: §"Motion model"; LINE/JOG_STEP — тот же потолок и на RZ, суставный ход
#: T2.J2 — только на XYZ; RZ там = J1+J2+J4, лерпится вместе с суставами,
#: см. docstring модуля «одна правда TLM_RZ»).
MAX_STEP_MM = 100 / 3

# Опкоды, ещё не реализованные -> NAK E_INTERNAL после проверки opcode/argc/busy
# (с T2.3, часть B, — пусто; механизм оставлен для следующих опкодов).
_UNIMPLEMENTED_OPS: frozenset[str] = frozenset()

#: TLM_WDG_STATE (§3.4): 0 выкл / 1 взведён / 2 сработал.
TLM_WDG_OFF = 0
TLM_WDG_ARMED = 1
TLM_WDG_TRIPPED = 2

# Мост ПЧ (§10.1): адреса и масштабы — ТОЛЬКО из `Services/vfd_comm` (единственный
# источник протокола моста, решение лида T2.3-B). sim здесь — сторона ПРОШИВКИ моста
# (ретрансляция mailbox и зеркало статуса); физика ПЧ/ленты — в инжектируемом `belt`.
#: Публичный адрес начала команды ПЧ (RUN, DIR, FREQ) — сторож jog плагина хоста.
VFD_CMD_ADDR = VFD_REG_CMD_RUN
_SIM_CURRENT_RAW = 150  # 15.0 А (CURRENT_SCALE 10), как v1 — зеркало статуса, не модель ПЧ
_SIM_DCBUS_RAW = 5400  # 540.0 В (DCBUS_SCALE 10), как v1
#: Лента без явного `belt`: та же скорость, что у v1 `RobotSimCore(enc_rate=7)`.
_DEFAULT_ENC_RATE = 7
# P_BELT_DIR (params.md): 0 +X, 1 +Y, 2 −X, 3 −Y -> единичный вектор оси ленты.
_BELT_AXES = {0: (1.0, 0.0), 1: (0.0, 1.0), 2: (-1.0, 0.0), 3: (0.0, -1.0)}
# P_BELT_FACTOR — мм/имп ×1e-5 (14447 -> 0.14447 мм/имп).
_BELT_FACTOR_SCALE = 1e-5

_ERR_NAME = {code: name for name, code in ERR.items()}

# Коды действия записи сценария (§7.1); 7+ — резерв -> R_ACTION.
_SC_ACTIONS = frozenset(ACT.values())

# В FAULT (TLM_ACTIVITY=5) принимаются только эти опкоды — остальные NAK E_BUSY (contract §FAULT).
_FAULT_WHITELIST = frozenset({"PING", "CLEAR_ERR", "PARAM_GET", "PARAM_SET", "SERVO"})

# JOG_CONT: направление -> (индекс оси в pos [x,y,z,rz], знак движения).
_JOG_AXIS_MAP = {
    1: (0, 1),  # X+
    2: (0, -1),  # X-
    3: (1, 1),  # Y+
    4: (1, -1),  # Y-
    5: (2, 1),  # Z+
    6: (2, -1),  # Z-
    7: (3, 1),  # RZ+
    8: (3, -1),  # RZ-
}

# Параметры рабочей зоны, из которых собирается geometry.Workspace (contract §"Zone").
_WS_PARAM_NAMES = (
    "P_WS_R_MIN",
    "P_WS_R_MAX",
    "P_WS_Z_MIN",
    "P_WS_Z_MAX",
    "P_WS_RZ_MIN",
    "P_WS_RZ_MAX",
    "P_WS_ANG_MIN",
    "P_WS_ANG_MAX",
    "P_WS_BOX_EN",
    "P_WS_X_MIN",
    "P_WS_X_MAX",
    "P_WS_Y_MIN",
    "P_WS_Y_MAX",
)

#: >= адреса последнего регистра v2-карты + 1 (покрывает PMIR_DICT = 0x3082).
REG_SPACE_SIZE_V2 = max(addr + REG_COUNT.get(name, 1) for name, addr in REG.items())


class RobotSimCoreV2:
    """Конечный автомат симулятора Delta v2 над массивом регистров ``self.regs``."""

    def __init__(
        self,
        regs: list[int] | None = None,
        *,
        fw_build: int = 0,
        model: RobotModel | None = None,
        belt: BeltDrive | None = None,
        on_event: Callable[[str], None] | None = None,
        on_job_done: Callable[[dict], None] | None = None,
    ) -> None:
        """T2.3, часть B: `belt` — модель ленты (`None` -> скорость v1 `enc_rate=7`);
        `on_event(text)` — строка на событие (формат — докстринг модуля);
        `on_job_done(event)` — словарь v1 на DONE каждого CVT_JOB. Исключения
        колбэков ядро не ловит (как v1) — защита на стороне хоста."""
        self.regs: list[int] = [0] * REG_SPACE_SIZE_V2 if regs is None else regs
        self._belt = belt if belt is not None else BeltDrive.from_enc_rate(_DEFAULT_ENC_RATE, TICK_INTERVAL_S)
        self._on_event = on_event
        self._on_job_done = on_job_done
        self._encoder = 0
        #: Счёт ПРИНЯТЫХ CVT_JOB с 1 — `index` события `on_job_done` (не seq команды).
        self._job_index = 0
        #: (seq, имя опкода) последней принятой команды — для строки `DONE` журнала.
        self._active_op: tuple[int, str] | None = None
        #: Код неисправности ПЧ: попадает в статус моста (0x1214) на пульсе VFD_FLAG, на ленту не влияет.
        self.vfd_fault_code: int = 0
        self._vfd_link_down = False
        self._wdg_armed = False
        self._wdg_last_hb = 0
        self._wdg_t = 0.0
        self._fw_build = fw_build
        # T2.K: тип робота сменный (RobotModel) — по умолчанию SCARA. Порядок
        # относительно _boot() не важен (_boot модель не читает), но модель нужна
        # уже с первой команды хода — выставляется до неё, а не лениво.
        self.model: RobotModel = model if model is not None else ScaraModel()
        self._op_by_code = {code: name for name, code in OP.items()}
        # Эффективные значения параметров — per-instance (И8: несколько роботов
        # не должны делить состояние через модульные глобалы).
        self._values: dict[int, int] = {}
        self._active: dict | None = None
        self._last_stop = 0
        self._last_seq = 0
        self._last_response: tuple[int, int, int, list[int]] = (0, 0, 0, [])
        # T2.2: счётчик-заглушка стопа ПЧ (T2.3 подключит настоящий мост), симуляционное
        # время (сумма dt, для поводка JOG_LEASE) и отложенный SOFT-стоп посреди хода.
        self.vfd_stop_requests = 0
        self._time_s = 0.0
        self._pending_soft: int | None = None
        self._boot()

    # ------------------------------------------------------------------ #
    # Хранилище
    # ------------------------------------------------------------------ #

    def attach(self, regs: list[int]) -> None:
        """Подменить хранилище на внешний живой список (как v1 sim_core.py).

        Текущее состояние копируется в новый список, дальше core мутирует его.
        Не атомарно (copy-then-reassign) — тот же компромисс, что в v1.
        """
        regs[: len(self.regs)] = self.regs
        self.regs = regs
        # T2.J2: суставы — состояние, заводится при (пере)загрузке позы (см. `_boot`).
        # `ik` — часть контракта `RobotModel` (Protocol), не опциональна (минорная 6
        # ревью T2.J2 — подставные модели теста дополнены `ik`, не код защитой здесь).
        self._joints = self.model.ik(self._read_pose_eng(), self.regs[REG["TLM_HAND"]])

    def read(self, address: int, count: int = 1) -> list[int]:
        """Прочитать блок регистров."""
        return list(self.regs[address : address + count])

    def write(self, address: int, values: list[int]) -> None:
        """Записать блок регистров (чистое хранение — реакция в tick())."""
        for i, v in enumerate(values):
            self.regs[address + i] = int(v) & 0xFFFF

    # ------------------------------------------------------------------ #
    # Загрузка
    # ------------------------------------------------------------------ #

    def _boot(self) -> None:
        self.regs[REG["TLM_PROTO_VER"]] = CONSTANTS["PROTO_VER"]
        self.regs[REG["TLM_FW_BUILD"]] = self._fw_build

        valid = self._mirror_is_valid()
        for pid, meta in PARAMS.items():
            value = meta["default"]
            if valid:
                raw = self.regs[REG["PMIR"] + pid]
                decoded = self._decode(raw, meta["signed"])
                if meta["min"] <= decoded <= meta["max"]:
                    value = decoded
            self._values[pid] = value

        for pid in PARAMS:
            self._write_mirror_slot(pid)
        self.regs[REG["PMIR_MAGIC"]] = CONSTANTS["PMIR_MAGIC_VALUE"]
        self.regs[REG["PMIR_DICT"]] = DICT_FINGERPRINT
        self.regs[REG["PMIR_CRC"]] = self._mirror_crc()

        self.regs[REG["TLM_CFG_EPOCH"]] = self._values[PARAM_ID["P_CONFIG_EPOCH"]]
        self.regs[REG["TLM_CFG_PENDING"]] = 0

        # STOP_REQ, оставшийся в регистре с прошлого запуска — "уже обработан":
        # эхо в TLM_STOP_ACK есть, но действие (abort/servo) не выполняется.
        self._last_stop = self.regs[REG["STOP_REQ"]]
        self.regs[REG["TLM_STOP_ACK"]] = self._last_stop

        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
        # Рестарт посреди хода: команды больше нет, MOVING=1 остался бы навсегда (ревью T2.1).
        self.regs[REG["TLM_MOVING"]] = 0
        # T2.3: Override в простое — P_SPD_DEFAULT (§3.4 TLM_SPD_PCT).
        self.regs[REG["TLM_SPD_PCT"]] = self._values[PARAM_ID["P_SPD_DEFAULT"]]
        # T2.3, часть B: сторож взводится только ИЗМЕНЕНИЕМ HB_PC после старта (§9.2) —
        # значение, оставшееся в регистре с прошлого запуска, изменением не считается.
        self._wdg_last_hb = self.regs[REG["HB_PC"]]
        self.regs[REG["TLM_WDG_STATE"]] = TLM_WDG_OFF
        # Энкодер продолжает счёт из регистров (рестарт с regs=old.regs), свежие — с 0.
        self._encoder = self.regs[REG["TLM_ENC"]] | (self.regs[REG["TLM_ENC"] + 1] << 16)
        self._write_belt_tlm()
        self.regs[REG["TLM_SERVO"]] = 1
        self.regs[REG["TLM_DO_MASK"]] = 0
        # T2.2: свежий дом — рука в дефолтной конфигурации (contract §"Motion model").
        self.regs[REG["TLM_HAND"]] = self._values[PARAM_ID["P_HAND"]]
        home_pose = (
            to_eng("P_HOME_X", self._values[PARAM_ID["P_HOME_X"]]),
            to_eng("P_HOME_Y", self._values[PARAM_ID["P_HOME_Y"]]),
            to_eng("P_HOME_Z", self._values[PARAM_ID["P_HOME_Z"]]),
            to_eng("P_HOME_RZ", self._values[PARAM_ID["P_HOME_RZ"]]),
        )
        # T2.J2: суставы — состояние, заводится при (пере)загрузке позы (docstring
        # модуля). `ik` — часть контракта `RobotModel` (Protocol), не опциональна
        # (минорная 6 ревью T2.J2 — подставные модели теста дополнены `ik`, не
        # код защитой здесь).
        self._set_pose_and_joints(home_pose, self.model.ik(home_pose, self.regs[REG["TLM_HAND"]]))

        # Идемпотентность после рестарта программы: последний ответ
        # восстанавливается из уже записанных регистров, чтобы повтор seq
        # сразу после рестарта не исполнился заново (см. отчёт T2.1).
        self._last_seq = self.regs[REG["RES_SEQ"]]
        # Мусор в RES_RVALC (> 8) при повторе seq затёр бы STOP_REQ/HB_PC за блоком RES (ревью T2.1).
        rvalc = min(self.regs[REG["RES_RVALC"]], REG_COUNT["RES_RVALS"])
        rvals = list(self.regs[REG["RES_RVALS"] : REG["RES_RVALS"] + rvalc])
        self._last_response = (
            self.regs[REG["RES_STATUS"]],
            self.regs[REG["RES_ERRNO"]],
            rvalc,
            rvals,
        )

    def _mirror_is_valid(self) -> bool:
        if self.regs[REG["PMIR_MAGIC"]] != CONSTANTS["PMIR_MAGIC_VALUE"]:
            return False
        if self.regs[REG["PMIR_DICT"]] != DICT_FINGERPRINT:
            return False
        return self.regs[REG["PMIR_CRC"]] == self._mirror_crc()

    # ------------------------------------------------------------------ #
    # Кодирование параметров и CRC зеркала
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encode(value: int, signed: bool) -> int:
        """Инженерное значение -> u16 (two's complement для signed)."""
        return value & 0xFFFF

    @staticmethod
    def _decode(raw: int, signed: bool) -> int:
        """u16 -> инженерное значение (two's complement для signed)."""
        if signed and raw >= 0x8000:
            return raw - 65536
        return raw

    def _write_mirror_slot(self, pid: int) -> None:
        meta = PARAMS[pid]
        self.regs[REG["PMIR"] + pid] = self._encode(self._values[pid], meta["signed"])

    def _mirror_crc(self) -> int:
        """CRC16/MODBUS по возрастанию id, u16 little-endian, свёрнутый до 15 бит."""
        data = bytearray()
        for pid in sorted(PARAMS):
            raw = self.regs[REG["PMIR"] + pid] & 0xFFFF
            data += raw.to_bytes(2, "little")
        return crc16_modbus(bytes(data)) & 0x7FFF

    # ------------------------------------------------------------------ #
    # Поза и рабочая зона (T2.2)
    # ------------------------------------------------------------------ #

    def _read_pose_eng(self) -> tuple[float, float, float, float]:
        """Поза из регистров TLM_X/Y/Z/RZ в инженерных единицах (мм/°)."""
        return (
            self._decode(self.regs[REG["TLM_X"]], True) / 10.0,
            self._decode(self.regs[REG["TLM_Y"]], True) / 10.0,
            self._decode(self.regs[REG["TLM_Z"]], True) / 10.0,
            self._decode(self.regs[REG["TLM_RZ"]], True) / 10.0,
        )

    def _write_pose(self, pos: tuple[float, float, float, float] | list[float]) -> None:
        """Записать интерполируемую позу в регистры (округление до 0.1 мм/°)."""
        x, y, z, rz = pos
        self.regs[REG["TLM_X"]] = self._encode(round(x * 10), True)
        self.regs[REG["TLM_Y"]] = self._encode(round(y * 10), True)
        self.regs[REG["TLM_Z"]] = self._encode(round(z * 10), True)
        self.regs[REG["TLM_RZ"]] = self._encode(round(rz * 10), True)

    def _set_pose_and_joints(
        self, pos: tuple[float, float, float, float] | list[float], joints: tuple[float, ...] | None
    ) -> None:
        """T2.J2: единственное место, пишущее позу + `self._joints` (состояние) +
        `TLM_HAND` вместе — `joints()` больше не пересчитывает `ik` по требованию.

        `joints`, если не `None`, ДОЛЖНЫ уже соответствовать `pos` (посчитаны
        вызывающим — `ik` при загрузке/LINE/JOG, lerp суставного хода) — не
        пересчитываются здесь заново, иначе состояние теряет точность лерпа
        (докстринг `joints()`/свойство 4 приёмки T2.J2).

        `TLM_HAND` выводится из знака `joints[1]` (J2, SCARA-правило, ⚑ GATE-1 —
        6-осевая рука потребует метод модели, не заводится здесь заранее):
        `J2 < 0` -> 1 (левая), `J2 > 0` -> 0 (правая), `J2 == 0` (вытянутая рука,
        конфигурация локтя не определена знаком) — регистр НЕ трогается.
        """
        self._write_pose(pos)
        self._joints = joints
        if joints is not None:
            j2 = joints[1]
            if j2 < 0.0:
                self.regs[REG["TLM_HAND"]] = 1
            elif j2 > 0.0:
                self.regs[REG["TLM_HAND"]] = 0

    def _resolve_joint_target(
        self, j_end: tuple[float, ...]
    ) -> tuple[tuple[int, int, int, list[int]] | None, tuple[float, ...] | None]:
        """T2.J2 §Q2 — вердикт cto по RZ (`docs/reviews/2026-09-27_robot-v2-task-T2.J2-cto.md`):
        правило «J4 — ближайший оборот» ОТОЗВАНО (несовместимо с «TLM_RZ = цель», давало
        скачок TLM_RZ на 717.6°/тик и `fk(joints)[3] != TLM_RZ` после DONE). J4 — СЫРОЙ
        (`ik` как есть, без перемотки ±360), проверяется в ОДНОМ цикле наравне с
        J1/J2/Z на `model.joint_limits` — вне предела (включая J4) -> `NAK E_RANGE
        [R_OUT_OF_ZONE]` (⚑ GATE-1, docstring модуля)."""
        for value, limit in zip(j_end, self.model.joint_limits):
            if limit is None:
                continue
            lo, hi = limit
            if not (lo <= value <= hi):
                return (NAK, ERR["E_RANGE"], 1, [REASON["R_OUT_OF_ZONE"]]), None
        return None, j_end

    def _workspace(self) -> Workspace:
        """Собрать geometry.Workspace из текущих эффективных P_WS_* параметров."""
        eng = {name: to_eng(name, self._values[PARAM_ID[name]]) for name in _WS_PARAM_NAMES}
        return Workspace.from_params(eng)

    def joints(self) -> tuple[float, ...] | None:
        """Суставы — СОСТОЯНИЕ симулятора (T2.J2), не пересчёт `ik(позы, TLM_HAND)`
        по требованию: `self._joints`, заводится/продвигается в `_boot`/`attach`/
        `_progress_move`/`_progress_jog` через `_set_pose_and_joints` — единственное
        место записи. Отличие от T2.K важно посреди хода/после обрыва: `ik` от
        ОКРУГЛЁННОЙ до 0.1мм позы отличается от точного состояния лерпа на
        0.01-0.03° (свойство 4 приёмки T2.J2) — состояние возвращает точное значение.

        Для окна-вида (T2.V): рисовать звенья руки, а не только точку TCP.

        `None` — ДОСТИЖИМОЕ поведение (ревью T2.K, находка 1), не аномалия:
        зона прошивки (`P_WS_*`, правда прошивки, проверяется `_check_motion`)
        и досягаемость модели (`|l1-l2| .. l1+l2` у `ScaraModel`) — две
        НЕЗАВИСИМЫЕ границы. Точка, прошедшая проверку зоны при ходе, может
        лежать вне досягаемости модели, если `P_WS_R_MAX > l1+l2` или
        `P_WS_R_MIN < |l1-l2|` (штатно — если длины звеньев с шильдика короче,
        чем дефолтная `P_WS_R_MAX=600` уже настроенной зоны). Воспроизведение:
        `P_WS_R_MAX=700` (шире дефолтной досягаемости 600), `PTP_MOVE JOINT`
        на `(650, 0)` -> `ACK`, `joints()` -> `None`. Вызывающий (T2.V) обязан
        обработать `None` сам (рисовать только TCP-точку без цепи звеньев) —
        `model.chain_points(core.joints())` упадёт `TypeError` на `None`.
        """
        return self._joints

    def _check_motion(
        self, target: tuple[float, float, float, float], line: bool
    ) -> tuple[tuple[int, int, int, list[int]] | None, tuple[float, ...] | None]:
        """Общая проверка цели хода (после проверки формата аргумента в обработчике).

        Порядок из контракта: E_NO_SERVO -> точка в зоне -> (JOINT/HOME) предел
        суставов (T2.J2 §Q2, ⚑ GATE-1) -> (LINE) рука -> (LINE) отрезок. Возвращает
        `(NAK-кортеж или None, j_end или None)` — `j_end` уже проверенный на пределы
        (J4 сырой, без перемотки — вердикт cto по RZ), чтобы `_start_move` не
        пересчитывал `ik` заново.
        Предел суставов пропускается, если `ik(target, P_HAND)` вернул `None`
        (недосягаемость модели по радиусу) — это фолбэк T2.J на прямую в Cartesian,
        предел суставов с ним НЕ путается (свойство 2 приёмки T2.J2).
        """
        if self.regs[REG["TLM_SERVO"]] == 0:
            return (NAK, ERR["E_NO_SERVO"], 0, []), None
        reason, j_end = self._check_target(
            self._workspace(), target, line, self._read_pose_eng(), self.regs[REG["TLM_HAND"]]
        )
        if reason != 0:
            return (NAK, ERR["E_RANGE"], 1, [reason]), None
        return None, j_end

    def _check_target(
        self,
        ws: Workspace,
        target: tuple[float, float, float, float],
        line: bool,
        start: tuple[float, float, float, float],
        hand: int,
    ) -> tuple[int, tuple[float, ...] | None]:
        """Проверка цели одного хода без побочных эффектов — общая для одиночного
        хода (`_check_motion`) и записи сценария (`_sc_validate`, T2.3).

        Порядок: точка в зоне -> (JOINT) предел суставов -> (LINE) рука `hand`
        против `P_HAND` -> (LINE) отрезок `start -> target`. Возвращает
        `(причина R_* или 0, j_end или None)`.
        """
        reason = self.model.check_point(ws, target)
        if reason != 0:
            return reason, None
        if not line:
            j_end = self.model.ik(target, self._values[PARAM_ID["P_HAND"]])
            if j_end is not None:
                nak, j_end = self._resolve_joint_target(j_end)
                if nak is not None:
                    return nak[3][0], None
            return 0, j_end
        if hand != self._values[PARAM_ID["P_HAND"]]:
            return REASON["R_HAND"], None
        return self.model.check_segment(ws, start, target), None

    def _start_move(
        self,
        seq: int,
        target: tuple[float, float, float, float],
        speed: float,
        *,
        joint: bool,
        activity: int,
        j_end: tuple[float, ...] | None = None,
        spd_pct: int | None = None,
    ) -> None:
        """Завести активный ход. JOINT/HOME (T2.J2 §Q2/Q3): `j_start` — ТЕКУЩЕЕ
        состояние (``self._joints``), не пересчёт ``ik(start_pose)``; `j_end` уже
        разрешён вызывающим (`_check_motion` -> `_resolve_joint_target`) — проверка
        пределов, J4 сырой; не пересчитывается здесь. Длительность = max(декартова,
        суставная) (§Q3), выражена эквивалентной длиной `path_len`, чтобы
        продвижение за тик оставалось `min(speed*dt, MAX_STEP_MM)` тем же кодом,
        что у Cartesian-хода (см. ``_progress_move``)."""
        start_pose = self._read_pose_eng()
        self._active = {
            "type": "move",
            "seq": seq,
            "pos": start_pose,
            "target": target,
            "speed": speed,
            "joint": joint,
        }
        if joint:
            j_start = self._joints
            delta = tuple(t - p for t, p in zip(target, start_pose))
            xyz_dist = math.sqrt(delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2)
            path_len = max(xyz_dist, abs(delta[3]))
            if j_start is not None and j_end is not None and speed > 0:
                spd_l = self._values[PARAM_ID["P_SPD_L"]]
                pct_frac = speed / spd_l if spd_l > 0 else 0.0
                spd_j_frac = self._values[PARAM_ID["P_SPD_J"]] / 100.0
                joint_time = 0.0
                for j0, j1, v_max in zip(j_start, j_end, self.model.joint_speed):
                    v = v_max * spd_j_frac * pct_frac
                    if v > 0:
                        joint_time = max(joint_time, abs(j1 - j0) / v)
                duration = max(path_len / speed, joint_time)
                path_len = duration * speed
            self._active.update(
                {
                    "j_start": j_start,
                    "j_end": j_end,
                    "path_len": path_len,
                    "travelled": 0.0,
                }
            )
        if spd_pct is not None:
            # T2.3: текущий Override, % (§3.4) — пишется на старте каждого хода.
            self.regs[REG["TLM_SPD_PCT"]] = spd_pct
        self.regs[REG["TLM_ACTIVITY"]] = activity
        self.regs[REG["TLM_MOVING"]] = 1

    # ------------------------------------------------------------------ #
    # Мotion-цикл
    # ------------------------------------------------------------------ #

    def tick(self, dt_s: float | None = None) -> None:
        """Один тик: heartbeat -> плоскость STOP_REQ -> mailbox -> прогресс команды.

        Всё время ядра — сумма `dt_s` (T2.3): стенные часы не читаются.
        Внутри сценария mailbox здесь НЕ опрашивается — только на EXACT-точке
        (`_sc_record_done`, §7.2 п.4); одиночные ходы — каждый тик, как в T2.2.
        """
        dt = TICK_INTERVAL_S if dt_s is None else dt_s
        if not (math.isfinite(dt) and dt > 0):
            dt = 0.0  # NaN/inf/отрицательный dt (скачок часов у вызывающего) — время не прошло (ревью T2.2)
        self._time_s += dt
        self.regs[REG["TLM_HB_ROBOT"]] = (self.regs[REG["TLM_HB_ROBOT"]] + 1) & 0xFFFF
        self._handle_stop()
        # T2.3, часть B: сторож и мост ПЧ — каждый тик, и внутри сценария (ADR-RC-015/016).
        self._handle_wdg()
        if not self._in_scenario():
            self._handle_mailbox()
        self._handle_vfd()
        # Энкодер — после _handle_vfd: команда этого тика уже действует на его приращение (как v1).
        self._encoder += self._belt.advance(dt)
        self._write_belt_tlm()
        self._progress(dt)

    def _in_scenario(self) -> bool:
        return self._active is not None and self._active.get("sc") is not None

    # --- плоскость STOP_REQ ---

    def _handle_stop(self) -> None:
        value = self.regs[REG["STOP_REQ"]]
        if value == self._last_stop:
            return
        self._last_stop = value
        # Уровень 0 в §8 не определён: регистр изменился — значит, намерение остановиться; такой
        # стоп обрывает команду как HARD (без серво и ПЧ) — безопасная сторона (решение ревью T2.2).
        level = value % 4
        # HALT гасит серво и шлёт стоп ПЧ ДО записи ERR_EVT (И5) — в простое тоже (contract §"Stop plane").
        if level == STOP_LEVEL["HALT"]:
            self.regs[REG["TLM_SERVO"]] = 0
            self._vfd_stop()
        if self._active is not None:
            if level == STOP_LEVEL["SOFT"] and self._active["type"] in ("move", "sc_delay", "cvt"):
                # SOFT посреди хода — pending: ход продолжается до цели, STOP_ACK
                # ещё не пишется (contract §"Stop plane"); JOG_CONT сюда не попадает.
                # Сценарий (T2.3): pending до ближайшей EXACT-точки (§7.2 п.4),
                # LINE_PASS его не обслуживает — `_sc_record_done`.
                self._pending_soft = value
                return
            self._pending_soft = None
            self._abort(ERR["E_ABORTED"], self._active["seq"])
        self.regs[REG["TLM_STOP_ACK"]] = value

    # --- сторожевой таймер (§9; T2.3, часть B) ---

    def _handle_wdg(self) -> None:
        """Каждый тик (и в сценарии — ADR-RC-016). Время — сумма `dt_s` (`_time_s`).

        Взвод — изменение `HB_PC` (§9.2), повторный — следующее изменение после
        срабатывания (A5). `P_WDG_TIMEOUT_MS = 0` — выключен, `TLM_WDG_STATE = 0`.
        Просрочка: стоп ПЧ, обрыв активности `E_WDG_TIMEOUT`, `TLM_WDG_STATE = 2`;
        серво остаётся (§9.4)."""
        timeout_ms = self._values[PARAM_ID["P_WDG_TIMEOUT_MS"]]
        hb = self.regs[REG["HB_PC"]]
        if hb != self._wdg_last_hb:
            self._wdg_last_hb = hb
            self._wdg_t = self._time_s
            if timeout_ms > 0:
                self._wdg_armed = True
                self.regs[REG["TLM_WDG_STATE"]] = TLM_WDG_ARMED
        if timeout_ms == 0:
            self._wdg_armed = False
            self.regs[REG["TLM_WDG_STATE"]] = TLM_WDG_OFF
            return
        if self._wdg_armed and self._time_s - self._wdg_t > timeout_ms / 1000.0:
            self._wdg_armed = False
            self._vfd_stop()
            self.regs[REG["TLM_WDG_STATE"]] = TLM_WDG_TRIPPED
            seq = self._active["seq"] if self._active is not None else 0
            fault = self.regs[REG["TLM_ACTIVITY"]] == TLM_ACTIVITY_FAULT
            self._abort(ERR["E_WDG_TIMEOUT"], seq, fault=fault)

    # --- мост ПЧ (§10; T2.3, часть B): сторона прошивки, физика — в `self._belt` ---

    def command_vfd(
        self,
        *,
        run: bool | None = None,
        freq_hz: float | None = None,
        reverse: bool | None = None,
    ) -> None:
        """Записать частичную команду ПЧ в mailbox — семантика v1
        `RobotSimCore.command_vfd`: пишутся только переданные поля, затем
        `VFD_FLAG` отдельной последней записью; применяется на ближайшем `tick()`
        (`_handle_vfd`), не сразу."""
        if run is not None:
            self.write(VFD_REG_CMD_RUN, [1 if run else 0])
        if reverse is not None:
            self.write(VFD_REG_CMD_DIR, [1 if reverse else 0])
        if freq_hz is not None:
            self.write(VFD_REG_CMD_FREQ, [round(freq_hz * VFD_FREQ_SCALE)])
        self.write(VFD_REG_FLAG, [1])

    def _handle_vfd(self) -> None:
        """Пульс `VFD_FLAG` -> команда в `belt` + зеркало статуса (как v1 `_handle_vfd`).
        Каждый тик, и в сценарии (ADR-RC-016)."""
        if self.regs[VFD_REG_FLAG] != 1:
            return
        run = self.regs[VFD_REG_CMD_RUN] == 1
        reverse = self.regs[VFD_REG_CMD_DIR] == 1
        freq = self.regs[VFD_REG_CMD_FREQ]
        self._belt.command(run=run, freq_hz=freq / VFD_FREQ_SCALE, reverse=reverse)
        if self.regs[VFD_REG_CMD_RESET] == 1:
            self.regs[VFD_REG_CMD_RESET] = 0
        self._write_vfd_status(run, freq, reverse)
        self.regs[VFD_REG_FLAG] = 0

    def _write_vfd_status(self, run: bool, freq_raw: int, reverse: bool) -> None:
        st = VFD_REG_ST_BASE
        self.regs[st + 0] = 1 if run else 0
        self.regs[st + 1] = freq_raw if run else 0
        self.regs[st + 2] = _SIM_CURRENT_RAW if run else 0
        self.regs[st + 3] = _SIM_DCBUS_RAW
        self.regs[st + 4] = self.vfd_fault_code & 0xFFFF
        self.regs[st + 5] = (VFD_STATE_REV if reverse else VFD_STATE_FWD) if run else VFD_STATE_STOP
        self.regs[st + 6] = (self.regs[st + 6] + 1) % 32767  # heartbeat моста

    def _vfd_stop(self) -> None:
        """Стоп ПЧ (HALT, сторож): ленту останавливает `belt.command(run=False)`.
        Командный mailbox 0x1200..0x1202 не трогается (его сравнивает сторож jog
        хоста) — меняется только зеркало статуса."""
        self.vfd_stop_requests += 1
        self._belt.command(run=False, freq_hz=0.0, reverse=False)
        self._write_vfd_status(False, 0, False)

    def inject_vfd_link_fault(self) -> None:
        """Тестовый хук (A1): обрыв связи с ПЧ состоялся — счёт `P_VFD_LINK_FAILS`
        опросов сжат в момент вызова, сразу async `E_VFD_LINK`. Одно событие на
        обрыв: повтор без `clear_vfd_link_fault()` нового события не даёт (§10.5).
        Активность не обрывается (спека не велит)."""
        if self._vfd_link_down:
            return
        self._vfd_link_down = True
        self.regs[REG["TLM_ERR_SEQ"]] = 0
        self.regs[REG["TLM_ERRNO_LAST"]] = ERR["E_VFD_LINK"]
        self.regs[REG["TLM_ERR_EVT"]] = (self.regs[REG["TLM_ERR_EVT"]] + 1) & 0xFFFF
        self._emit_err(0, ERR["E_VFD_LINK"])

    def clear_vfd_link_fault(self) -> None:
        """Связь с ПЧ восстановлена — следующий обрыв даст новое событие."""
        self._vfd_link_down = False

    # --- лента: публичные имена, которые читает плагин хоста ---

    def _write_belt_tlm(self) -> None:
        value = self._encoder & 0xFFFFFFFF
        self.regs[REG["TLM_ENC"]] = value & 0xFFFF  # DW: младшее слово на чётном адресе
        self.regs[REG["TLM_ENC"] + 1] = (value >> 16) & 0xFFFF
        mm_s = max(-32767, min(32767, round(self._belt.mm_s)))
        self.regs[REG["TLM_BELT_MMS"]] = self._encode(mm_s, True)

    @property
    def belt(self) -> BeltDrive:
        """Модель ленты (`belt.*` хоста: калибровка, статус)."""
        return self._belt

    @property
    def belt_mm_s(self) -> float:
        """Точная текущая скорость ленты, мм/с."""
        return self._belt.mm_s

    @property
    def encoder(self) -> int:
        """Значение энкодера (= `TLM_ENC`, растёт от `belt.advance(dt)` каждый тик)."""
        return self._encoder

    def _abort(self, errno: int, seq: int, *, fault: bool = False) -> None:
        """Оборвать активную команду: поза замирает (не трогается здесь), одно событие ERR_EVT (И5).

        Ожидающий SOFT снимается при ЛЮБОМ обрыве и получает эхо в STOP_ACK после
        события: команды, которую он ждал, больше нет (иначе он «съел» бы следующий ход).
        """
        pending, self._pending_soft = self._pending_soft, None
        sc_end = None
        if self._in_scenario():
            # T2.3: итог оборванного сценария — число ЗАВЕРШЁННЫХ записей (не count).
            sc_end = self._active["sc"]
            self.regs[REG["TLM_SC_DONE_N"]] = sc_end["i"]
        # T2.3: на любом выходе Override возвращается к P_SPD_DEFAULT (§7.2 п.5).
        self.regs[REG["TLM_SPD_PCT"]] = self._values[PARAM_ID["P_SPD_DEFAULT"]]
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_FAULT if fault else TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        self.regs[REG["TLM_ERR_SEQ"]] = seq
        self.regs[REG["TLM_ERRNO_LAST"]] = errno
        self.regs[REG["TLM_ERR_EVT"]] = (self.regs[REG["TLM_ERR_EVT"]] + 1) & 0xFFFF
        self._active = None
        if pending is not None:
            self.regs[REG["TLM_STOP_ACK"]] = pending
        self._emit_err(seq, errno)
        if sc_end is not None:
            self._emit(f"[v2] SC end id={sc_end['id']} done_n={sc_end['i']}")

    def _emit(self, text: str) -> None:
        """Строка события журнала (`on_event`); формат — докстринг модуля."""
        if self._on_event is not None:
            self._on_event(text)

    def _emit_err(self, seq: int, errno: int) -> None:
        self._emit(f"[v2] ERR seq={seq} errno={errno} {_ERR_NAME.get(errno, '?')}")

    def _op_name_of(self, seq: int) -> str:
        if self._active_op is not None and self._active_op[0] == seq:
            return self._active_op[1]
        return "?"

    def _finish_done(self, active: dict) -> None:
        """Штатное завершение (не ошибка): ACTIVITY/MOVING, DONE_SEQ последним (И5).

        T2.J2: `TLM_HAND` больше не выставляется здесь принудительно в `P_HAND` —
        он уже следует состоянию на каждой записи позы (`_set_pose_and_joints`,
        находка ревью T2.J №3, свойство 3 приёмки T2.J2)."""
        self.regs[REG["TLM_SPD_PCT"]] = self._values[PARAM_ID["P_SPD_DEFAULT"]]  # T2.3: IDLE -> P_SPD_DEFAULT
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        self._active = None
        self.regs[REG["TLM_DONE_SEQ"]] = active["seq"]
        self._emit(f"[v2] DONE seq={active['seq']} op={self._op_name_of(active['seq'])}")

    def inject_motion_fault(self) -> None:
        """Тестовый хук: авария контроллера движения (E_MOTION_FAULT, TLM_ACTIVITY=5).

        Если команда активна — обрывается (поза замирает), TLM_ERR_SEQ = её seq;
        иначе TLM_ERR_SEQ = 0. Работает и в простое (contract §FAULT).
        """
        seq = self._active["seq"] if self._active is not None else 0
        self._abort(ERR["E_MOTION_FAULT"], seq, fault=True)

    # --- прогресс активной команды ---

    def _progress(self, dt: float) -> None:
        if self._active is None:
            return
        if self._active["type"] == "jog":
            self._progress_jog(dt)
        elif self._active["type"] == "sc_delay":
            self._progress_sc_delay(dt)
        elif self._active.get("cvt") is not None and self._active["cvt"]["phase"] == "approach":
            self._progress_cvt_approach(dt)
        else:
            self._progress_move(dt)

    def _cartesian_step(
        self,
        pos: tuple[float, float, float, float],
        target: tuple[float, float, float, float],
        speed: float,
        dt: float,
    ) -> tuple[float, float, float, float]:
        """Шаг min(v*dt, MAX_STEP_MM) вдоль прямой pos->target (LINE/JOG_STEP путь,
        и однотиковый фолбэк JOINT-хода при ``ik``/``fk`` -> ``None``, T2.J).

        Путь = max(XYZ-дистанция, |ΔRZ|); пересчёт от текущей позы на каждом тике
        математически эквивалентен накоплению от старта (прямая линия) — см. отчёт T2.2.
        """
        delta = tuple(t - p for t, p in zip(target, pos))
        xyz_dist = math.sqrt(delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2)
        path_len = max(xyz_dist, abs(delta[3]))
        step = min(speed * dt, MAX_STEP_MM)
        if step >= path_len:
            return target
        frac = step / path_len
        return tuple(p + frac * d for p, d in zip(pos, delta))

    def _continuity_joints(self, pos: tuple[float, float, float, float]) -> tuple[float, ...] | None:
        """LINE/JOG (свойство 9 приёмки T2.J2): суставы следуют состоянию —
        `ik(pos, TLM_HAND)` КАК ЕСТЬ, без поправок J4 (вердикт cto по RZ: правило
        «ближайший оборот» отозвано — J4 сырой везде, TLM_RZ = fk(_joints)[3] без
        mod 360, см. docstring модуля)."""
        return self.model.ik(pos, self.regs[REG["TLM_HAND"]])

    def _joint_tick_capped(
        self,
        active: dict,
        prev_pos: tuple[float, float, float, float],
        candidate_travelled: float,
        dt: float,
    ) -> tuple[float, tuple[float, ...] | None, tuple[float, float, float, float]]:
        """⚑ HARD CAP (решение ведущего 2026-09-27): декартово смещение позы за
        один тик <= MAX_STEP_MM И в суставном ходе — если `fk` кандидатной доли
        тика даёт больший шаг (нелинейность `fk` у вытянутой руки), доля тика
        урезается бисекцией. Возвращает (новый ``travelled``, суставы или `None`,
        поза)."""

        def pose_at(travelled: float) -> tuple[tuple[float, ...], tuple[float, float, float, float] | None]:
            # Пустой ход (цель == текущая поза, path_len == 0): делить нечего, ход
            # уже в конце (sim-zero-path); финал `_progress_move` снэпит в target.
            frac = travelled / active["path_len"] if active["path_len"] > 0 else 1.0
            joints = tuple(j0 + frac * (j1 - j0) for j0, j1 in zip(active["j_start"], active["j_end"]))
            return joints, self.model.fk(joints)

        ws = self._workspace()

        def cart_dist(fk_pos: tuple[float, float, float, float]) -> float:
            # Округление до регистрового разрешения (0.1 мм, как `_write_pose`) —
            # тест меряет шаг МЕЖДУ ЗАПИСАННЫМИ (округлёнными) позами, не между
            # точными внутренними float; без округления здесь бисекция сходится к
            # потолку по точным координатам и пропускает через округление лишние
            # ~0.05-0.1мм на каждой оси (найдено прогоном свойства 1 приёмки
            # T2.J2 тестера, `test_seam_target_other_hand_moves_within_step_cap`,
            # developer, ДО какой-либо инъекции ведущего). Если обычное округление
            # выводит из зоны (та же точка у границы r=l1+l2) — бисекция меряет
            # расстояние ДО клэмп-кандидата (`_clamp_pose_to_zone`), иначе она может
            # принять долю тика, чей клэмпнутый (записываемый) шаг сам превышает
            # потолок (решение ведущего 2026-09-27, найдено этим же прогоном).
            rounded = tuple(round(v * 10) / 10.0 for v in fk_pos)
            a_r = (
                rounded[:3]
                if self._check_point_xy(ws, rounded[0], rounded[1]) == 0
                else self._clamp_pose_to_zone(fk_pos)[:3]
            )
            b_r = tuple(round(v * 10) / 10.0 for v in prev_pos[:3])
            return math.sqrt(sum((a - b) ** 2 for a, b in zip(a_r, b_r)))

        joints, fk_pos = pose_at(candidate_travelled)
        if fk_pos is None:
            # ponytail: суставы из lerp двух ДОСТИЖИМЫХ концов сами вне модели —
            # фолбэк на декартов шаг ТОЛЬКО для этого тика, travelled не
            # продвигаем (следующий тик пробует ту же долю снова, T2.J design).
            # Major 4 ревью T2.J2: состояние НЕ стирается в None — держим lerp
            # суставов ПРИ ТЕКУЩЕМ (не продвинутом) travelled, иначе следующий
            # JOINT стартует без состояния и падает на прямую в Cartesian.
            fallback = self._cartesian_step(prev_pos, active["target"], active["speed"], dt)
            current_joints, _ = pose_at(active["travelled"])
            return active["travelled"], current_joints, fallback
        if cart_dist(fk_pos) <= MAX_STEP_MM + 1e-9:
            return candidate_travelled, joints, fk_pos
        lo = active["travelled"]
        lo_joints, lo_fk = pose_at(lo)
        lo_pos = lo_fk if lo_fk is not None else prev_pos
        hi = candidate_travelled
        for _ in range(30):
            mid = (lo + hi) / 2.0
            mid_joints, mid_pos = pose_at(mid)
            if mid_pos is not None and cart_dist(mid_pos) <= MAX_STEP_MM + 1e-9:
                lo, lo_joints, lo_pos = mid, mid_joints, mid_pos
            else:
                hi = mid
        return lo, lo_joints, lo_pos

    def _check_point_xy(self, ws: Workspace, x: float, y: float) -> int:
        """T2.J2, вердикт cto по RZ (§2 «Зона RZ — только на командной цели»):
        промежуточные проверки зоны посреди суставного хода (клэмп у вытянутой
        руки, потолок шага) смотрят ТОЛЬКО XY (кольцо `r`, угловой сектор, XY-бокс)
        — не Z/RZ. `geometry.py` не меняем: зовём `check_point` с z/rz, внутри зоны
        ПО ПОСТРОЕНИЮ — нижние границы `ws.z_min`/`ws.rz_min` (границы включительны),
        чтобы они не участвовали в решении. Прежняя подстановка `rz=0.0` ломалась при
        зоне RZ без нуля (`P_WS_RZ_MIN=10°`: каждая XY-проверка отвергала точку, клэмп
        к зоне бессилен, в регистре r=600.031 — блокер итерации 2 ревью T2.J2).
        Вырожденная зона (`rz_min > rz_max`) не содержит ни одной точки: сюда ход не
        доходит — цель отвергается `_check_motion` при приёме (NAK `E_RANGE`), а
        `PARAM_SET` посреди хода отвергается (замер teamlead, итерация 3 ревью)."""
        return self.model.check_point(ws, (x, y, ws.z_min, ws.rz_min))

    def _clamp_pose_to_zone(self, pos: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """Решение ведущего 2026-09-27 (свойство 1 приёмки T2.J2, `r=600.028` >
        `r_max=600.0`): у вытянутой руки (r у ГРАНИЦЫ круга `l1+l2`) независимое
        округление x/y до 0.1 мм (регистровое разрешение) может УВЕЛИЧИТЬ r настолько,
        что округлённая поза покидает зону — тот же класс, что ревью T2.2 для JOG_CONT
        (`_progress_jog`, проверка округлённой позы перед записью). Если округление к
        БЛИЖАЙШЕМУ выводит из зоны (по XY — `_check_point_xy`, вердикт cto по RZ) —
        округлить x/y К НУЛЮ (`math.trunc`): |x|,|y| только уменьшаются, r только
        уменьшается. Если и так вне зоны — вернуть round-к-ближайшему как есть
        (честно недорешено, см. отчёт «Итерация 2»)."""
        ws = self._workspace()
        rounded = tuple(round(v * 10) / 10.0 for v in pos)
        if self._check_point_xy(ws, rounded[0], rounded[1]) == 0:
            return rounded
        x, y, z, rz = pos
        trunc_xy = (math.trunc(x * 10) / 10.0, math.trunc(y * 10) / 10.0)
        candidate = (trunc_xy[0], trunc_xy[1], rounded[2], rounded[3])
        if self._check_point_xy(ws, candidate[0], candidate[1]) == 0:
            return candidate
        return rounded

    def _progress_move(self, dt: float) -> None:
        """Ход (PTP_MOVE/HOME/JOG_STEP): JOINT/HOME (T2.J/T2.J2) — по суставам модели
        через ``self._active["j_start"/"j_end"/"path_len"/"travelled"]`` (см.
        ``_start_move``), с жёстким потолком декартова шага (``_joint_tick_capped``);
        иначе (LINE/JOG_STEP, или ``ik`` не достал старт/цель) — прямая в Cartesian.
        Суставы состояния обновляются на КАЖДОМ тике через `_set_pose_and_joints`
        (T2.J2 §Q2) — не только на JOINT.
        """
        active = self._active
        pos = active["pos"]
        target = active["target"]
        if active.get("j_start") is not None and active.get("j_end") is not None:
            # ⚑ БЛОКЕР 1 ревью T2.J2: финальный тик ТОЖЕ идёт через `_joint_tick_capped`
            # (кандидат зажат `path_len`) — раньше `candidate_travelled >= path_len`
            # прыгал сразу в `target` в обход потолка (найден шаг 145.2мм при смене
            # руки, MAX_STEP_MM=33.3). Снэп в `target`/`j_end` ТОЧНО — только когда
            # бисекция реально дотянула до `path_len` без урезания; иначе ход
            # продолжается на следующем тике с честного капнутого `new_pos`.
            step_eq = min(active["speed"] * dt, MAX_STEP_MM)
            candidate_travelled = min(active["travelled"] + step_eq, active["path_len"])
            new_travelled, new_joints, new_pos = self._joint_tick_capped(active, pos, candidate_travelled, dt)
            active["travelled"] = new_travelled
            # `new_pos == target` без `path_len`: декартов фолбэк (`fk -> None` посреди
            # пути) дошёл до цели сам, `travelled` заморожен — суставы тоже в `j_end`
            # (одна правда: `fk(joints()) == поза` после DONE, minor итерации 2 ревью).
            if new_travelled >= active["path_len"] - 1e-9 or new_pos == target:
                new_pos = target
                new_joints = active["j_end"]
            # Клэмп зоны трогает позу ТОЛЬКО когда обычное округление её из зоны
            # выводит (свойство 1 приёмки T2.J2, r=600.028>r_max) — иначе не
            # трогать new_pos вовсе: `_clamp_pose_to_zone` в быстром пути
            # математически то же значение, что вернул бы `_write_pose`, но
            # предвычисленное округление здесь и повторное округление там —
            # разные float-выражения одной величины, ULP-шум на них за ~1400
            # тиков `test_duration_follows_slowest_joint` даёт расхождение в
            # 2 тика (найдено этим прогоном, решение — не трогать общий путь).
            elif self._check_point_xy(self._workspace(), *[round(v * 10) / 10.0 for v in new_pos[:2]]) != 0:
                new_pos = self._clamp_pose_to_zone(new_pos)
        else:
            new_pos = self._cartesian_step(pos, target, active["speed"], dt)
            new_joints = self._continuity_joints(new_pos)
        active["pos"] = new_pos
        self._set_pose_and_joints(new_pos, new_joints)
        if new_pos == target:
            if active.get("sc") is not None:
                self._sc_arrived(active)  # T2.3: сценарий сам решает про SOFT/DONE/следующий отрезок
            elif active.get("cvt") is not None:
                self._cvt_arrived(active)  # T2.3-B: захват -> укладка -> DONE
            elif self._pending_soft is not None:
                self._abort(ERR["E_ABORTED"], active["seq"])  # эхо отложенного SOFT пишет _abort
            else:
                self._finish_done(active)

    def _progress_jog(self, dt: float) -> None:
        """JOG_CONT: шаг min(speed*dt, MAX_STEP_MM) вдоль одной оси (потолок срабатывает только на большом dt —
        при штатных P_JOG_CONT_MAX и тике 10 мс speed*dt меньше него).

        Завершается DONE по таймауту поводка (JOG_LEASE не менялся дольше
        P_JOG_LEASE_MS) или на краю зоны (шаг не делается, поза остаётся внутри).
        """
        active = self._active
        lease_reg = self.regs[REG["JOG_LEASE"]]
        if lease_reg != active["lease"]:
            active["lease"] = lease_reg
            active["lease_t"] = self._time_s
        threshold_s = self._values[PARAM_ID["P_JOG_LEASE_MS"]] / 1000.0
        if self._time_s - active["lease_t"] > threshold_s:
            self._finish_done(active)
            return
        pos = list(active["pos"])
        pos[active["axis"]] += active["sign"] * min(active["speed"] * dt, MAX_STEP_MM)
        # Проверяется поза, какой её увидит ПК (округление до 0.1): от неё стартует следующая
        # команда; float-поза внутри при округлённой снаружи блокировала бы любой LINE (ревью T2.2).
        reason = self.model.check_point(self._workspace(), tuple(round(v * 10) / 10 for v in pos))
        if reason != 0:
            self._finish_done(active)
            return
        active["pos"] = pos
        pos_t = (pos[0], pos[1], pos[2], pos[3])
        self._set_pose_and_joints(pos_t, self._continuity_joints(pos_t))

    # --- CVT_JOB (T2.3, часть B; protocol-spec §5) ---

    def _cvt_tracked_xy(self, cvt: dict) -> tuple[float, float]:
        """Следимая точка pick (прошивка v1 `main_actual.lua:465-467`):
        `trav = (TLM_ENC − ecap) × P_BELT_FACTOR`, сдвиг вдоль оси `P_BELT_DIR`.
        Разность энкодеров — по модулю 2^32 со знаком (переполнение DW)."""
        diff = (self._encoder - cvt["ecap"]) & 0xFFFFFFFF
        if diff >= 1 << 31:
            diff -= 1 << 32
        trav = diff * self._values[PARAM_ID["P_BELT_FACTOR"]] * _BELT_FACTOR_SCALE
        ux, uy = _BELT_AXES[self._values[PARAM_ID["P_BELT_DIR"]]]
        return cvt["pick_x"] + ux * trav, cvt["pick_y"] + uy * trav

    def _progress_cvt_approach(self, dt: float) -> None:
        """Подход: каждый тик цель = следимая точка (JOINT, высота pick); промах —
        точка вне кольца `P_ZONE_MIN..P_ZONE_MAX` (не `P_WS_*`) на любом тике
        подхода, включая тик приёма -> async `E_ZONE_TRIP`."""
        active = self._active
        cvt, seq = active["cvt"], active["seq"]
        tx, ty = self._cvt_tracked_xy(cvt)
        r = math.hypot(tx, ty)
        r_min = to_eng("P_ZONE_MIN", self._values[PARAM_ID["P_ZONE_MIN"]])
        r_max = to_eng("P_ZONE_MAX", self._values[PARAM_ID["P_ZONE_MAX"]])
        if not (r_min <= r <= r_max):
            self._cvt_miss(seq, tx, ty)
            return
        target = (tx, ty, cvt["pick_z"], cvt["pick_rz"])
        j_end = self.model.ik(target, self._values[PARAM_ID["P_HAND"]])
        if j_end is not None:
            nak, j_end = self._resolve_joint_target(j_end)
            if nak is not None:  # следимая точка ушла за пределы суставов — тоже промах
                self._cvt_miss(seq, tx, ty)
                return
        self._start_move(
            seq, target, cvt["speed"], joint=True, activity=TLM_ACTIVITY_CVT, j_end=j_end, spd_pct=cvt["spd_pct"]
        )
        self._active["cvt"] = cvt
        self._progress_move(dt)

    def _cvt_miss(self, seq: int, x: float, y: float) -> None:
        self.regs[REG["TLM_MISS_COUNT"]] = (self.regs[REG["TLM_MISS_COUNT"]] + 1) & 0xFFFF
        self._emit(f"[v2] CVT miss seq={seq} x={x:.1f} y={y:.1f}")
        self._abort(ERR["E_ZONE_TRIP"], seq)  # DONE_SEQ не пишется

    def _cvt_arrived(self, active: dict) -> None:
        """Приход: в точку pick — захват мгновенный, старт JOINT в укладку; в
        укладку — DONE_SEQ, затем `on_job_done`. Отложенный SOFT — обрыв на
        приходе (между примитивами), как у одиночного хода."""
        cvt, seq = active["cvt"], active["seq"]
        if self._pending_soft is not None:
            self._abort(ERR["E_ABORTED"], seq)
            return
        if cvt["phase"] == "approach":
            cvt["phase"] = "place"
            x, y = active["target"][0], active["target"][1]
            self._emit(f"[v2] CVT grip seq={seq} x={x:.1f} y={y:.1f}")
            self._start_move(
                seq,
                cvt["place"],
                cvt["speed"],
                joint=True,
                activity=TLM_ACTIVITY_CVT,
                j_end=cvt["place_j_end"],
                spd_pct=cvt["spd_pct"],
            )
            self._active["cvt"] = cvt
            return
        self._finish_done(active)
        if self._on_job_done is not None:
            self._on_job_done(
                {
                    "index": cvt["index"],
                    "x_mm": cvt["pick_x"],
                    "y_mm": cvt["pick_y"],
                    "ecap": cvt["ecap"],
                    "t": self._time_s,  # время sim; хост заменяет на monotonic перед сценой
                }
            )

    # --- сценарий SC_RUN (T2.3, часть A; protocol-spec §7) ---

    def _sc_validate(self, offset: int, count: int) -> tuple[list[dict] | None, tuple[int, int, int, list[int]] | None]:
        """§7.2 п.1-2: прочитать записи `offset..offset+count-1` и проверить ВСЁ
        до первого движения. Без побочных эффектов (NAK не оставляет следов).

        Порядок внутри записи: KIND -> последняя не LINE_PASS -> ACTION -> APARAM
        -> точка/пределы суставов/рука/отрезок (`_check_target`). Первая ошибка
        -> NAK `E_SC_RECORD [индекс в срезе, R_*]`.
        """
        ws = self._workspace()
        start = self._read_pose_eng()
        hand = self.regs[REG["TLM_HAND"]]
        p_hand = self._values[PARAM_ID["P_HAND"]]
        acc_meta = PARAMS[PARAM_ID["P_ACC_L"]]
        records: list[dict] = []
        for i in range(count):
            base = REG["SC_BUF"] + (offset + i) * CONSTANTS["SC_STRIDE"]
            x, y, z, rz, op, aparam = self.regs[base : base + CONSTANTS["SC_STRIDE"]]
            kind, action = op & 0xFF, op >> 8

            def nak(reason: int, idx: int = i) -> tuple[None, tuple[int, int, int, list[int]]]:
                return None, (NAK, ERR["E_SC_RECORD"], 2, [idx, reason])

            if kind not in KIND.values():
                return nak(REASON["R_KIND"])
            if i == count - 1 and kind == KIND["LINE_PASS"]:
                return nak(REASON["R_LAST_PASS"])
            if action not in _SC_ACTIONS:
                return nak(REASON["R_ACTION"])
            if action in (ACT["DO_ON"], ACT["DO_OFF"]):
                aparam_ok = 1 <= aparam <= 16
            elif action == ACT["SPEED_PCT"]:
                aparam_ok = 1 <= aparam <= 100
            elif action == ACT["ACCEL"]:
                aparam_ok = acc_meta["min"] <= aparam <= acc_meta["max"]
            elif action == ACT["ACCUR"]:
                aparam_ok = aparam in (0, 1)
            else:
                aparam_ok = True  # NONE — APARAM игнорируется; DELAY_MS — весь u16, мс
            if not aparam_ok:
                return nak(REASON["R_APARAM"])
            target = tuple(self._decode(v, True) / 10.0 for v in (x, y, z, rz))
            line = kind != KIND["JOINT"]
            reason, j_end = self._check_target(ws, target, line, start, hand)
            if reason != 0:
                return nak(reason)
            if not line and j_end is not None:
                hand = p_hand  # JOINT ставит руку P_HAND (§7.3) — LINE после него допустим
            records.append({"target": target, "kind": kind, "action": action, "aparam": aparam, "j_end": j_end})
            start = target
        return records, None

    def _sc_start_record(self, seq: int, sc: dict) -> None:
        """Завести ход текущей записи сценария — тем же `_start_move`, что и одиночный ход."""
        rec = sc["records"][sc["i"]]
        speed = self._values[PARAM_ID["P_SPD_L"]] * sc["spd_pct"] / 100.0
        self._start_move(
            seq,
            rec["target"],
            speed,
            joint=rec["kind"] == KIND["JOINT"],
            activity=TLM_ACTIVITY_SCENARIO,
            j_end=rec["j_end"],
            spd_pct=sc["spd_pct"],
        )
        self._active["sc"] = sc

    def _sc_arrived(self, active: dict) -> None:
        """Тик прихода в точку записи: индекс (только EXACT) -> действие записи.
        `DELAY_MS > 0` переводит в паузу `sc_delay` — запись завершится на тике,
        где сумма `dt_s` догонит паузу (`_progress_sc_delay`), не на этом."""
        sc = active["sc"]
        rec = sc["records"][sc["i"]]
        if rec["kind"] != KIND["LINE_PASS"]:
            self.regs[REG["TLM_SC_INDEX"]] = sc["i"] + 1
        action, aparam = rec["action"], rec["aparam"]
        if action == ACT["DO_ON"]:
            self._set_do(aparam, 1)
        elif action == ACT["DO_OFF"]:
            self._set_do(aparam, 0)
        elif action == ACT["SPEED_PCT"]:
            sc["spd_pct"] = aparam
        elif action == ACT["ACCEL"]:
            sc["accel"] = aparam  # хранится, разгон sim не моделирует
        elif action == ACT["ACCUR"]:
            sc["accur"] = aparam  # хранится, точность sim не моделирует
        elif action == ACT["DELAY_MS"] and aparam > 0:
            self.regs[REG["TLM_MOVING"]] = 0
            self._active = {
                "type": "sc_delay",
                "seq": active["seq"],
                "sc": sc,
                "delay_s": aparam / 1000.0,
                "elapsed_s": 0.0,
            }
            return
        self._sc_record_done(active["seq"], sc)

    def _progress_sc_delay(self, dt: float) -> None:
        """`DELAY_MS`: только сумма `dt_s` тиков после тика прихода (время sim)."""
        active = self._active
        active["elapsed_s"] += dt
        if active["elapsed_s"] >= active["delay_s"] - 1e-9:
            self._sc_record_done(active["seq"], active["sc"])

    def _sc_record_done(self, seq: int, sc: dict) -> None:
        """Запись завершена (приход + действие). На EXACT-точке (§7.2 п.4):
        отложенный SOFT -> `E_ABORTED`; иначе опрос mailbox. Затем — DONE на
        последней записи или старт следующего отрезка в этом же тике."""
        exact = sc["records"][sc["i"]]["kind"] != KIND["LINE_PASS"]
        sc["i"] += 1
        if exact and self._pending_soft is not None:
            self._abort(ERR["E_ABORTED"], seq)  # эхо отложенного SOFT пишет _abort
            return
        if sc["i"] == sc["count"]:
            self.regs[REG["TLM_SC_ID"]] = sc["id"]
            self.regs[REG["TLM_SC_TOTAL"]] = sc["count"]
            self.regs[REG["TLM_SC_DONE_N"]] = sc["count"]
            self._finish_done(self._active)  # DONE_SEQ последним (И5)
            self._emit(f"[v2] SC end id={sc['id']} done_n={sc['count']}")
            return
        if exact:
            self._handle_mailbox()
        self._sc_start_record(seq, sc)

    # --- mailbox ---

    def _handle_mailbox(self) -> None:
        if self.regs[REG["CMD_FLAG"]] != 1:
            return
        seq = self.regs[REG["CMD_SEQ"]]
        opcode = self.regs[REG["CMD_OPCODE"]]
        argc = self.regs[REG["CMD_ARGC"]]
        args = list(self.regs[REG["CMD_ARGS"] : REG["CMD_ARGS"] + argc])
        self.regs[REG["CMD_FLAG"]] = 0

        if seq == self._last_seq:
            # Повтор последнего seq — не исполняется заново, ответ
            # переписывается тем же содержимым (RES_SEQ всё равно последним).
            status, errno, rvalc, rvals = self._last_response
            self._respond(seq, status, errno, rvalc, rvals)
            return

        status, errno, rvalc, rvals = self._execute(seq, opcode, argc, args)
        self._last_seq = seq
        self._last_response = (status, errno, rvalc, rvals)
        self._respond(seq, status, errno, rvalc, rvals)
        if status == ACK:
            opname = self._op_by_code.get(opcode, f"0x{opcode:02X}")
            if self._active is not None and self._active["seq"] == seq:
                self._active_op = (seq, opname)  # команда завела ход — её имя нужно строке DONE
            self._emit(f"[v2] CMD seq={seq} op={opname}")

    def _respond(self, seq: int, status: int, errno: int, rvalc: int, rvals: list[int]) -> None:
        self.regs[REG["RES_STATUS"]] = status
        self.regs[REG["RES_ERRNO"]] = errno
        self.regs[REG["RES_RVALC"]] = rvalc
        if rvals:
            self.write(REG["RES_RVALS"], rvals)
        if status == ACK:
            self.regs[REG["TLM_ACK_SEQ"]] = seq
        self.regs[REG["RES_SEQ"]] = seq  # И5: последняя запись ответа

    def _execute(self, seq: int, opcode: int, argc: int, args: list[int]) -> tuple[int, int, int, list[int]]:
        opname = self._op_by_code.get(opcode)
        if opname is None:
            return NAK, ERR["E_BAD_OPCODE"], 0, []
        spec = OP_SPEC[opname]
        if argc != spec["argc"]:
            return NAK, ERR["E_BAD_ARGC"], 0, []
        activity = self.regs[REG["TLM_ACTIVITY"]]
        if activity == TLM_ACTIVITY_FAULT:
            if opname not in _FAULT_WHITELIST:
                return NAK, ERR["E_BUSY"], 0, []
            busy = False  # FAULT: PARAM_SET любого apply-класса всё равно проходит.
        else:
            busy = activity != TLM_ACTIVITY_IDLE
            if busy and opname != "PARAM_SET" and spec["busy"] == "deny":
                return NAK, ERR["E_BUSY"], 0, []
        if opname in _UNIMPLEMENTED_OPS:
            return NAK, ERR["E_INTERNAL"], 0, []
        handler = getattr(self, f"_op_{opname.lower()}")
        return handler(args, busy, seq)

    # --- обработчики опкодов (busy/seq игнорируются там, где не нужны) ---

    def _op_ping(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        return ACK, 0, 2, [CONSTANTS["PROTO_VER"], self._fw_build]

    def _op_clear_err(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        self.regs[REG["TLM_ERRNO_LAST"]] = 0
        self.regs[REG["TLM_ERR_SEQ"]] = 0
        if self.regs[REG["TLM_ACTIVITY"]] == TLM_ACTIVITY_FAULT:
            self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
        return ACK, 0, 0, []

    def _op_servo(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        on = args[0]
        if on not in (0, 1):
            return NAK, ERR["E_RANGE"], 0, []
        self.regs[REG["TLM_SERVO"]] = on
        return ACK, 0, 0, []

    def _op_do_set(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        channel, value = args
        if not (1 <= channel <= 16) or value not in (0, 1):
            return NAK, ERR["E_RANGE"], 0, []
        self._set_do(channel, value)
        return ACK, 0, 0, []

    def _set_do(self, channel: int, value: int) -> None:
        """DO-канал 1..16 -> бит маски (общий для DO_SET и действий сценария)."""
        bit = 1 << (channel - 1)
        mask = self.regs[REG["TLM_DO_MASK"]]
        mask = (mask | bit) if value else (mask & ~bit)
        self.regs[REG["TLM_DO_MASK"]] = mask & 0xFFFF

    def _op_param_get(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        pid = args[0]
        meta = PARAMS.get(pid)
        if meta is None:
            return NAK, ERR["E_BAD_PARAM"], 0, []
        return ACK, 0, 1, [self._encode(self._values[pid], meta["signed"])]

    def _op_param_set(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        pid, raw = args
        meta = PARAMS.get(pid)
        if meta is None:
            return NAK, ERR["E_BAD_PARAM"], 0, []
        # busy: by_class — доступно во время команды только для apply=live (FAULT: busy=False всегда).
        if busy and meta["apply"] != "live":
            return NAK, ERR["E_BUSY"], 0, []
        value = self._decode(raw, meta["signed"])
        if not (meta["min"] <= value <= meta["max"]):
            return NAK, ERR["E_RANGE"], 0, []
        self._values[pid] = value
        self._write_mirror_slot(pid)
        self.regs[REG["PMIR_CRC"]] = self._mirror_crc()
        if pid == PARAM_ID["P_CONFIG_EPOCH"]:
            self.regs[REG["TLM_CFG_EPOCH"]] = value
        if pid == PARAM_ID["P_SPD_DEFAULT"] and self.regs[REG["TLM_ACTIVITY"]] == TLM_ACTIVITY_IDLE:
            self.regs[REG["TLM_SPD_PCT"]] = value  # T2.3: Override в простое следует P_SPD_DEFAULT
        if meta["apply"] == "reinit":
            self.regs[REG["TLM_CFG_PENDING"]] = 1
        return ACK, 0, 0, []

    def _op_param_apply(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        self.regs[REG["TLM_CFG_PENDING"]] = 0
        return ACK, 0, 0, []

    def _op_ptp_move(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        x, y, z, rz, kind, spd_pct = args
        if kind not in (KIND["LINE"], KIND["JOINT"]):
            return NAK, ERR["E_RANGE"], 1, [REASON["R_KIND"]]
        if spd_pct > 100:
            return NAK, ERR["E_RANGE"], 0, []
        target = (
            self._decode(x, True) / 10.0,
            self._decode(y, True) / 10.0,
            self._decode(z, True) / 10.0,
            self._decode(rz, True) / 10.0,
        )
        line = kind == KIND["LINE"]
        nak, j_end = self._check_motion(target, line)
        if nak is not None:
            return nak
        pct = spd_pct if spd_pct != 0 else self._values[PARAM_ID["P_SPD_DEFAULT"]]
        speed = self._values[PARAM_ID["P_SPD_L"]] * pct / 100.0
        self._start_move(seq, target, speed, joint=not line, activity=TLM_ACTIVITY_PTP, j_end=j_end, spd_pct=pct)
        return ACK, 0, 0, []

    def _op_home(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        (spd_pct,) = args
        if spd_pct > 100:
            return NAK, ERR["E_RANGE"], 0, []
        target = (
            to_eng("P_HOME_X", self._values[PARAM_ID["P_HOME_X"]]),
            to_eng("P_HOME_Y", self._values[PARAM_ID["P_HOME_Y"]]),
            to_eng("P_HOME_Z", self._values[PARAM_ID["P_HOME_Z"]]),
            to_eng("P_HOME_RZ", self._values[PARAM_ID["P_HOME_RZ"]]),
        )
        nak, j_end = self._check_motion(target, line=False)
        if nak is not None:
            return nak
        pct = spd_pct if spd_pct != 0 else self._values[PARAM_ID["P_SPD_DEFAULT"]]
        speed = self._values[PARAM_ID["P_SPD_L"]] * pct / 100.0
        self._start_move(seq, target, speed, joint=True, activity=TLM_ACTIVITY_PTP, j_end=j_end, spd_pct=pct)
        return ACK, 0, 0, []

    def _op_jog_step(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        dx, dy, dz, drz, spd_pct = args
        if spd_pct > 100:
            return NAK, ERR["E_RANGE"], 0, []
        dx_e = self._decode(dx, True) / 10.0
        dy_e = self._decode(dy, True) / 10.0
        dz_e = self._decode(dz, True) / 10.0
        jog_max = to_eng("P_JOG_MAX", self._values[PARAM_ID["P_JOG_MAX"]])
        if math.sqrt(dx_e**2 + dy_e**2 + dz_e**2) > jog_max:
            return NAK, ERR["E_RANGE"], 1, [REASON["R_JOG_TOO_LONG"]]
        # Цель — в сырых ×0.1: float-сумма 128.2 + (-28.2) даёт 99.99999999999999 < r_min (ревью T2.2).
        cur_raw = [self._decode(self.regs[REG[n]], True) for n in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ")]
        deltas = [self._decode(v, True) for v in (dx, dy, dz, drz)]
        target = tuple((c + d) / 10.0 for c, d in zip(cur_raw, deltas))
        nak, _j_end = self._check_motion(target, line=True)
        if nak is not None:
            return nak
        pct = spd_pct if spd_pct != 0 else self._values[PARAM_ID["P_SPD_JOG"]]
        speed = self._values[PARAM_ID["P_SPD_L"]] * pct / 100.0
        self._start_move(seq, target, speed, joint=False, activity=TLM_ACTIVITY_JOG, spd_pct=pct)
        return ACK, 0, 0, []

    def _op_cvt_job(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        """CVT_JOB (§5): сначала NAK по аргументам и модели (укладка — зона и
        пределы суставов; pick_z/RZ — диапазон зоны Z/RZ), промах по кольцу —
        только потом, async на первом тике подхода (этот же тик)."""
        ecap_lo, ecap_hi, px, py, pz, flags, qx, qy, qz, qrz = args
        if self.regs[REG["TLM_SERVO"]] == 0:
            return NAK, ERR["E_NO_SERVO"], 0, []

        def eng(raw: int) -> float:
            return self._decode(raw, True) / 10.0

        def param(name: str) -> float:
            return to_eng(name, self._values[PARAM_ID[name]])

        pick_z = eng(pz) if flags & 1 else param("P_PICK_Z")
        pick_rz = param("P_PICK_RZ")  # у CVT_JOB нет pick_rz (§5)
        if flags & 2:
            place = (eng(qx), eng(qy), eng(qz), eng(qrz))
        else:
            place = (param("P_PLACE_X"), param("P_PLACE_Y"), param("P_PLACE_Z"), param("P_PLACE_RZ"))
        ws = self._workspace()
        reason, place_j_end = self._check_target(ws, place, False, place, self.regs[REG["TLM_HAND"]])
        if reason != 0:
            return NAK, ERR["E_RANGE"], 1, [reason]
        if not (ws.z_min <= pick_z <= ws.z_max and ws.rz_min <= pick_rz <= ws.rz_max):
            return NAK, ERR["E_RANGE"], 1, [REASON["R_OUT_OF_ZONE"]]
        self._job_index += 1
        pct = self._values[PARAM_ID["P_SPD_DEFAULT"]]
        cvt = {
            "phase": "approach",
            "index": self._job_index,
            "ecap": ecap_lo | (ecap_hi << 16),
            "pick_x": eng(px),
            "pick_y": eng(py),
            "pick_z": pick_z,
            "pick_rz": pick_rz,
            "place": place,
            "place_j_end": place_j_end,
            "spd_pct": pct,
            "speed": self._values[PARAM_ID["P_SPD_L"]] * pct / 100.0,
        }
        self._active = {"type": "cvt", "seq": seq, "cvt": cvt}
        self.regs[REG["TLM_SPD_PCT"]] = pct
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_CVT
        self.regs[REG["TLM_MOVING"]] = 1
        return ACK, 0, 0, []

    def _op_sc_run(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        """SC_RUN (§7.2): E_SC_COUNT -> E_NO_SERVO -> весь срез (`_sc_validate`) -> ход."""
        count, sc_id, offset = args
        cap = CONSTANTS["SC_CAP"]
        if not (1 <= count <= cap) or offset + count > cap:
            return NAK, ERR["E_SC_COUNT"], 0, []
        if self.regs[REG["TLM_SERVO"]] == 0:
            return NAK, ERR["E_NO_SERVO"], 0, []
        records, nak = self._sc_validate(offset, count)
        if nak is not None:
            return nak
        sc = {
            "id": sc_id,
            "count": count,
            "records": records,
            "i": 0,
            "spd_pct": self._values[PARAM_ID["P_SPD_DEFAULT"]],
            "accel": self._values[PARAM_ID["P_ACC_L"]],
            "accur": self._values[PARAM_ID["P_ACCUR_DEFAULT"]],
        }
        self.regs[REG["TLM_SC_ID"]] = sc_id
        self.regs[REG["TLM_SC_TOTAL"]] = count
        self.regs[REG["TLM_SC_INDEX"]] = 0
        self.regs[REG["TLM_SC_DONE_N"]] = 0
        self._sc_start_record(seq, sc)
        self._emit(f"[v2] SC start id={sc_id} count={count}")
        return ACK, 0, 0, []

    def _op_jog_cont(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        direction, speed = args
        if direction not in _JOG_AXIS_MAP:
            return NAK, ERR["E_RANGE"], 0, []
        jog_cont_max = self._values[PARAM_ID["P_JOG_CONT_MAX"]]
        if speed == 0 or speed > jog_cont_max:
            return NAK, ERR["E_RANGE"], 0, []
        if self.regs[REG["TLM_SERVO"]] == 0:
            return NAK, ERR["E_NO_SERVO"], 0, []
        if self.regs[REG["TLM_HAND"]] != self._values[PARAM_ID["P_HAND"]]:
            return NAK, ERR["E_RANGE"], 1, [REASON["R_HAND"]]
        axis, sign = _JOG_AXIS_MAP[direction]
        self._active = {
            "type": "jog",
            "seq": seq,
            "axis": axis,
            "sign": sign,
            "speed": float(speed),
            "pos": list(self._read_pose_eng()),
            "lease": self.regs[REG["JOG_LEASE"]],
            "lease_t": self._time_s,
        }
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_JOG
        self.regs[REG["TLM_MOVING"]] = 1
        return ACK, 0, 0, []
