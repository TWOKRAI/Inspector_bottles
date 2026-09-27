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
Cartesian, включая JOINT — упрощение симулятора, реальная прошивка
интерполирует JOINT в суставах), ``JOG_CONT`` с поводком (``JOG_LEASE``) и
остановкой на краю зоны, проверка рабочей зоны через уже принятую
``programs/geometry.py`` (``Workspace``/``check_point``/``check_segment`` —
переиспользуются, не копируются), ``E_NO_SERVO`` для всех опкодов движения,
плоскость стопа с уровнями SOFT (pending для хода, abort now для jog) / HARD /
HALT, ``inject_motion_fault()`` (``FAULT``, ``TLM_ACTIVITY=5``) с gating
(только ``PING``/``CLEAR_ERR``/``PARAM_GET``/``PARAM_SET``/``SERVO``
разрешены). Упрощения симулятора: замедление стопа HARD (``P_DEC_STOP``) не
моделируется — поза замирает на тике обработки; JOINT-ход интерполируется в
декартовых координатах, а не по суставам.

Отложено: ``CVT_JOB``/``SC_RUN`` (NAK ``E_INTERNAL``), ``HB_PC``/watchdog,
мост ПЧ/лента, сценарии, TCP-сервер ``--protocol v2`` (T2.3); ``on_event``
(T2.4). v1-симулятор (``sim_core.py``) не используется и не импортируется —
новый протокол живёт в отдельном адресном пространстве.
"""

from __future__ import annotations

import math

# ponytail: CRC берётся из кодогена (тянет yaml); перенести в core/, если sim уедет туда, где yaml нет.
from Services.robot_comm.codegen import crc16_modbus
from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, KIND, OP, OP_SPEC, REASON, REG, REG_COUNT, STOP_LEVEL
from Services.robot_comm.programs.geometry import Workspace, check_point, check_segment

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
#: жёсткий потолок смещения позы за один тик (мм или °, contract §"Motion model").
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

    def __init__(self, regs: list[int] | None = None, *, fw_build: int = 0) -> None:
        self.regs: list[int] = [0] * REG_SPACE_SIZE_V2 if regs is None else regs
        self._fw_build = fw_build
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
        self.regs[REG["TLM_X"]] = self._encode(self._values[PARAM_ID["P_HOME_X"]], True)
        self.regs[REG["TLM_Y"]] = self._encode(self._values[PARAM_ID["P_HOME_Y"]], True)
        self.regs[REG["TLM_Z"]] = self._encode(self._values[PARAM_ID["P_HOME_Z"]], True)
        self.regs[REG["TLM_RZ"]] = self._encode(self._values[PARAM_ID["P_HOME_RZ"]], True)
        self.regs[REG["TLM_DO_MASK"]] = 0
        # T2.2: свежий дом — рука в дефолтной конфигурации (contract §"Motion model").
        self.regs[REG["TLM_HAND"]] = self._values[PARAM_ID["P_HAND"]]

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

    def _workspace(self) -> Workspace:
        """Собрать geometry.Workspace из текущих эффективных P_WS_* параметров."""
        eng = {name: to_eng(name, self._values[PARAM_ID[name]]) for name in _WS_PARAM_NAMES}
        return Workspace.from_params(eng)

    def _check_motion(
        self, target: tuple[float, float, float, float], line: bool
    ) -> tuple[int, int, int, list[int]] | None:
        """Общая проверка цели хода (после проверки формата аргумента в обработчике).

        Порядок из контракта: E_NO_SERVO -> точка в зоне -> (LINE) рука -> (LINE) отрезок.
        Возвращает готовый NAK-кортеж или None, если цель допустима.
        """
        if self.regs[REG["TLM_SERVO"]] == 0:
            return NAK, ERR["E_NO_SERVO"], 0, []
        ws = self._workspace()
        reason = check_point(ws, *target)
        if reason != 0:
            return NAK, ERR["E_RANGE"], 1, [reason]
        if line:
            if self.regs[REG["TLM_HAND"]] != self._values[PARAM_ID["P_HAND"]]:
                return NAK, ERR["E_RANGE"], 1, [REASON["R_HAND"]]
            cur = self._read_pose_eng()
            reason = check_segment(ws, cur[0], cur[1], target[0], target[1])
            if reason != 0:
                return NAK, ERR["E_RANGE"], 1, [reason]
        return None

    def _start_move(
        self,
        seq: int,
        target: tuple[float, float, float, float],
        speed: float,
        *,
        joint: bool,
        activity: int,
    ) -> None:
        self._active = {
            "type": "move",
            "seq": seq,
            "pos": self._read_pose_eng(),
            "target": target,
            "speed": speed,
            "joint": joint,
        }
        self.regs[REG["TLM_ACTIVITY"]] = activity
        self.regs[REG["TLM_MOVING"]] = 1

    # ------------------------------------------------------------------ #
    # Мotion-цикл
    # ------------------------------------------------------------------ #

    def tick(self, dt_s: float | None = None) -> None:
        """Один тик: heartbeat -> плоскость STOP_REQ -> mailbox -> прогресс команды."""
        dt = TICK_INTERVAL_S if dt_s is None else dt_s
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
        """Оборвать активную команду: поза замирает (не трогается здесь), одно событие ERR_EVT (И5)."""
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_FAULT if fault else TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        self.regs[REG["TLM_ERR_SEQ"]] = seq
        self.regs[REG["TLM_ERRNO_LAST"]] = errno
        self.regs[REG["TLM_ERR_EVT"]] = (self.regs[REG["TLM_ERR_EVT"]] + 1) & 0xFFFF
        self._active = None

    def _finish_done(self, active: dict) -> None:
        """Штатное завершение (не ошибка): ACTIVITY/MOVING, [HAND если JOINT], DONE_SEQ последним (И5)."""
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        if active.get("joint"):
            self.regs[REG["TLM_HAND"]] = self._values[PARAM_ID["P_HAND"]]
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

    def _progress_move(self, dt: float) -> None:
        """Ход (PTP_MOVE/HOME/JOG_STEP): шаг min(v*dt, MAX_STEP_MM) вдоль прямой к цели.

        Путь = max(XYZ-дистанция, |ΔRZ|); пересчёт от текущей позы на каждом тике
        математически эквивалентен накоплению от старта (прямая линия) — см. отчёт.
        """
        active = self._active
        pos = active["pos"]
        target = active["target"]
        delta = tuple(t - p for t, p in zip(target, pos))
        xyz_dist = math.sqrt(delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2)
        path_len = max(xyz_dist, abs(delta[3]))
        step = min(active["speed"] * dt, MAX_STEP_MM)
        if step >= path_len:
            new_pos = target
        else:
            frac = step / path_len
            new_pos = tuple(p + frac * d for p, d in zip(pos, delta))
        active["pos"] = new_pos
        self._write_pose(new_pos)
        if new_pos == target:
            if self._pending_soft is not None:
                pending = self._pending_soft
                self._pending_soft = None
                self._abort(ERR["E_ABORTED"], active["seq"])
                self.regs[REG["TLM_STOP_ACK"]] = pending
            else:
                self._finish_done(active)

    def _progress_jog(self, dt: float) -> None:
        """JOG_CONT: шаг speed*dt вдоль одной оси, без MAX_STEP_MM (не нужен при штатных P_JOG_CONT_MAX).

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
        pos[active["axis"]] += active["sign"] * active["speed"] * dt
        reason = check_point(self._workspace(), pos[0], pos[1], pos[2], pos[3])
        if reason != 0:
            self._finish_done(active)
            return
        active["pos"] = pos
        self._write_pose(pos)

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
        nak = self._check_motion(target, line)
        if nak is not None:
            return nak
        pct = spd_pct if spd_pct != 0 else self._values[PARAM_ID["P_SPD_DEFAULT"]]
        speed = self._values[PARAM_ID["P_SPD_L"]] * pct / 100.0
        self._start_move(seq, target, speed, joint=not line, activity=TLM_ACTIVITY_PTP)
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
        nak = self._check_motion(target, line=False)
        if nak is not None:
            return nak
        pct = spd_pct if spd_pct != 0 else self._values[PARAM_ID["P_SPD_DEFAULT"]]
        speed = self._values[PARAM_ID["P_SPD_L"]] * pct / 100.0
        self._start_move(seq, target, speed, joint=True, activity=TLM_ACTIVITY_PTP)
        return ACK, 0, 0, []

    def _op_jog_step(self, args: list[int], busy: bool, seq: int) -> tuple[int, int, int, list[int]]:
        dx, dy, dz, drz, spd_pct = args
        if spd_pct > 100:
            return NAK, ERR["E_RANGE"], 0, []
        dx_e = self._decode(dx, True) / 10.0
        dy_e = self._decode(dy, True) / 10.0
        dz_e = self._decode(dz, True) / 10.0
        drz_e = self._decode(drz, True) / 10.0
        jog_max = to_eng("P_JOG_MAX", self._values[PARAM_ID["P_JOG_MAX"]])
        if math.sqrt(dx_e**2 + dy_e**2 + dz_e**2) > jog_max:
            return NAK, ERR["E_RANGE"], 1, [REASON["R_JOG_TOO_LONG"]]
        cur = self._read_pose_eng()
        target = (cur[0] + dx_e, cur[1] + dy_e, cur[2] + dz_e, cur[3] + drz_e)
        nak = self._check_motion(target, line=True)
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
