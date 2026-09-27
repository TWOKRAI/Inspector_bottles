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

Отложено: ``CVT_JOB``/``SC_RUN`` (NAK ``E_INTERNAL``), ``HB_PC``/watchdog,
мост ПЧ/лента, сценарии, TCP-сервер ``--protocol v2`` (T2.3); ``on_event``
(T2.4). v1-симулятор (``sim_core.py``) не используется и не импортируется —
новый протокол живёт в отдельном адресном пространстве.

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

# ponytail: CRC берётся из кодогена (тянет yaml); перенести в core/, если sim уедет туда, где yaml нет.
from Services.robot_comm.codegen import crc16_modbus
from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, KIND, OP, OP_SPEC, REASON, REG, REG_COUNT, STOP_LEVEL
from Services.robot_comm.kinematics import RobotModel, ScaraModel
from Services.robot_comm.programs.geometry import Workspace

# ACK/NAK не входят в сгенерированный контракт (protocol-spec §4) -> литералы.
ACK = 1
NAK = 2

# ponytail: коды активности локальны для sim v2 — перенести в YAML/кодоген,
# когда та же таблица понадобится прошивке (T4).
TLM_ACTIVITY_IDLE = 0
TLM_ACTIVITY_PTP = 1
TLM_ACTIVITY_JOG = 2
TLM_ACTIVITY_FAULT = 5

#: dt по умолчанию, когда tick() вызван без аргумента (contract §"Motion model").
TICK_INTERVAL_S = 0.01
#: жёсткий потолок декартова смещения XYZ позы за один тик, мм (contract
#: §"Motion model"; LINE/JOG_STEP — тот же потолок и на RZ, суставный ход
#: T2.J2 — только на XYZ; RZ там = J1+J2+J4, лерпится вместе с суставами,
#: см. docstring модуля «одна правда TLM_RZ»).
MAX_STEP_MM = 100 / 3

# Опкоды, не реализованные ни в T2.1, ни в T2.2 (out of scope по контракту) -> NAK E_INTERNAL
# после проверки opcode/argc/busy.
_UNIMPLEMENTED_OPS = frozenset({"CVT_JOB", "SC_RUN"})

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

    def __init__(self, regs: list[int] | None = None, *, fw_build: int = 0, model: RobotModel | None = None) -> None:
        self.regs: list[int] = [0] * REG_SPACE_SIZE_V2 if regs is None else regs
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
        ws = self._workspace()
        reason = self.model.check_point(ws, target)
        if reason != 0:
            return (NAK, ERR["E_RANGE"], 1, [reason]), None
        j_end = None
        if not line:
            j_end = self.model.ik(target, self._values[PARAM_ID["P_HAND"]])
            if j_end is not None:
                nak, j_end = self._resolve_joint_target(j_end)
                if nak is not None:
                    return nak, None
        if line:
            if self.regs[REG["TLM_HAND"]] != self._values[PARAM_ID["P_HAND"]]:
                return (NAK, ERR["E_RANGE"], 1, [REASON["R_HAND"]]), None
            cur = self._read_pose_eng()
            reason = self.model.check_segment(ws, cur, target)
            if reason != 0:
                return (NAK, ERR["E_RANGE"], 1, [reason]), None
        return None, j_end

    def _start_move(
        self,
        seq: int,
        target: tuple[float, float, float, float],
        speed: float,
        *,
        joint: bool,
        activity: int,
        j_end: tuple[float, ...] | None = None,
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
        self.regs[REG["TLM_ACTIVITY"]] = activity
        self.regs[REG["TLM_MOVING"]] = 1

    # ------------------------------------------------------------------ #
    # Мotion-цикл
    # ------------------------------------------------------------------ #

    def tick(self, dt_s: float | None = None) -> None:
        """Один тик: heartbeat -> плоскость STOP_REQ -> mailbox -> прогресс команды."""
        dt = TICK_INTERVAL_S if dt_s is None else dt_s
        if not (math.isfinite(dt) and dt > 0):
            dt = 0.0  # NaN/inf/отрицательный dt (скачок часов у вызывающего) — время не прошло (ревью T2.2)
        self._time_s += dt
        self.regs[REG["TLM_HB_ROBOT"]] = (self.regs[REG["TLM_HB_ROBOT"]] + 1) & 0xFFFF
        self._handle_stop()
        self._handle_mailbox()
        self._progress(dt)

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
            self.vfd_stop_requests += 1
        if self._active is not None:
            if level == STOP_LEVEL["SOFT"] and self._active["type"] == "move":
                # SOFT посреди хода — pending: ход продолжается до цели, STOP_ACK
                # ещё не пишется (contract §"Stop plane"); JOG_CONT сюда не попадает.
                self._pending_soft = value
                return
            self._pending_soft = None
            self._abort(ERR["E_ABORTED"], self._active["seq"])
        self.regs[REG["TLM_STOP_ACK"]] = value

    def _abort(self, errno: int, seq: int, *, fault: bool = False) -> None:
        """Оборвать активную команду: поза замирает (не трогается здесь), одно событие ERR_EVT (И5).

        Ожидающий SOFT снимается при ЛЮБОМ обрыве и получает эхо в STOP_ACK после
        события: команды, которую он ждал, больше нет (иначе он «съел» бы следующий ход).
        """
        pending, self._pending_soft = self._pending_soft, None
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_FAULT if fault else TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        self.regs[REG["TLM_ERR_SEQ"]] = seq
        self.regs[REG["TLM_ERRNO_LAST"]] = errno
        self.regs[REG["TLM_ERR_EVT"]] = (self.regs[REG["TLM_ERR_EVT"]] + 1) & 0xFFFF
        self._active = None
        if pending is not None:
            self.regs[REG["TLM_STOP_ACK"]] = pending

    def _finish_done(self, active: dict) -> None:
        """Штатное завершение (не ошибка): ACTIVITY/MOVING, DONE_SEQ последним (И5).

        T2.J2: `TLM_HAND` больше не выставляется здесь принудительно в `P_HAND` —
        он уже следует состоянию на каждой записи позы (`_set_pose_and_joints`,
        находка ревью T2.J №3, свойство 3 приёмки T2.J2)."""
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        self._active = None
        self.regs[REG["TLM_DONE_SEQ"]] = active["seq"]

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
            frac = travelled / active["path_len"]
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
            if self._pending_soft is not None:
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
        bit = 1 << (channel - 1)
        mask = self.regs[REG["TLM_DO_MASK"]]
        mask = (mask | bit) if value else (mask & ~bit)
        self.regs[REG["TLM_DO_MASK"]] = mask & 0xFFFF
        return ACK, 0, 0, []

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
        self._start_move(seq, target, speed, joint=not line, activity=TLM_ACTIVITY_PTP, j_end=j_end)
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
        self._start_move(seq, target, speed, joint=True, activity=TLM_ACTIVITY_PTP, j_end=j_end)
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
        self._start_move(seq, target, speed, joint=False, activity=TLM_ACTIVITY_JOG)
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
