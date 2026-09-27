"""Ядро симулятора робота протокола v2 (T2.1, plans/robot-protocol-v2).

Эмулирует Motion-цикл прошивки Delta v2 НАД массивом регистров:

- mailbox (``CMD_*``/``RES_*``) — приём одной команды за тик, ACK/NAK, повтор
  последнего ``seq`` не исполняется заново (идемпотентность, включая повтор
  после рестарта программы — последний ответ восстанавливается из регистров
  при загрузке);
- зеркало параметров (``PMIR`` + ``PMIR_MAGIC``/``PMIR_CRC``/``PMIR_DICT``) —
  валидируется при загрузке (magic + fingerprint словаря + CRC16/MODBUS),
  битые слоты откатываются к дефолту поштучно;
- плоскость ``STOP_REQ`` — действует только на ИЗМЕНЕНИЕ значения, HARD/HALT
  обрывают активную команду, HALT дополнительно гасит серво.

Реализовано в T2.1: ``PING``, ``CLEAR_ERR``, ``SERVO``, ``DO_SET``,
``PARAM_SET``/``PARAM_GET``/``PARAM_APPLY``, и placeholder ``PTP_MOVE`` (без
интерполяции и проверки зоны — просто "висит" фиксированное число тиков,
затем телепортируется в цель). ``HOME``/``JOG_STEP``/``JOG_CONT``/``CVT_JOB``/
``SC_RUN`` — NAK ``E_INTERNAL`` (не реализованы).

Отложено: интерполяция/зона/``E_NO_SERVO`` (T2.2); ``HB_PC``/``JOG_LEASE``/
watchdog/мост ПЧ/CVT/сценарии/TCP-сервер ``--protocol v2`` (T2.3);
``on_event`` (T2.4). v1-симулятор (``sim_core.py``) не используется и не
импортируется — новый протокол живёт в отдельном адресном пространстве.
"""

from __future__ import annotations

# ponytail: CRC берётся из кодогена (тянет yaml); перенести в core/, если sim уедет туда, где yaml нет.
from Services.robot_comm.codegen import crc16_modbus
from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, OP, OP_SPEC, REG, REG_COUNT, STOP_LEVEL

# ACK/NAK не входят в сгенерированный контракт (protocol-spec §4) -> литералы.
ACK = 1
NAK = 2

# ponytail: коды активности локальны для sim v2 — перенести в YAML/кодоген,
# когда та же таблица понадобится прошивке (T4).
TLM_ACTIVITY_IDLE = 0
TLM_ACTIVITY_PTP = 1

# ponytail: заглушка до T2.2 (интерполяция, зона, E_NO_SERVO) — PTP_MOVE
# просто "висит" фиксированное число тиков, затем телепортируется в цель.
PTP_PLACEHOLDER_TICKS = 4

# Опкоды, не реализованные в T2.1 (out of scope по контракту) -> NAK E_INTERNAL
# после проверки opcode/argc.
_UNIMPLEMENTED_OPS = frozenset({"HOME", "JOG_STEP", "JOG_CONT", "CVT_JOB", "SC_RUN"})

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
    # Мotion-цикл
    # ------------------------------------------------------------------ #

    def tick(self, dt_s: float | None = None) -> None:
        """Один тик: heartbeat -> плоскость STOP_REQ -> mailbox -> прогресс команды."""
        self.regs[REG["TLM_HB_ROBOT"]] = (self.regs[REG["TLM_HB_ROBOT"]] + 1) & 0xFFFF
        self._handle_stop()
        self._handle_mailbox()
        self._progress()

    # --- плоскость STOP_REQ ---

    def _handle_stop(self) -> None:
        value = self.regs[REG["STOP_REQ"]]
        if value == self._last_stop:
            return
        self._last_stop = value
        level = value % 4
        # HALT гасит серво ДО записи ERR_EVT: серво входит в блок события (И5).
        if level == STOP_LEVEL["HALT"]:
            self.regs[REG["TLM_SERVO"]] = 0
        if self._active is not None and level in (STOP_LEVEL["HARD"], STOP_LEVEL["HALT"]):
            seq = self._active["seq"]
            self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
            self.regs[REG["TLM_MOVING"]] = 0
            self.regs[REG["TLM_ERR_SEQ"]] = seq
            self.regs[REG["TLM_ERRNO_LAST"]] = ERR["E_ABORTED"]
            self.regs[REG["TLM_ERR_EVT"]] = (self.regs[REG["TLM_ERR_EVT"]] + 1) & 0xFFFF
            self._active = None
        self.regs[REG["TLM_STOP_ACK"]] = value

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
        busy = self.regs[REG["TLM_ACTIVITY"]] != TLM_ACTIVITY_IDLE
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
        # busy: by_class — доступно во время команды только для apply=live.
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
        # ponytail: заглушка до T2.2 — kind/spd_pct принимаются, но не влияют
        # на поведение (нет интерполяции, нет проверки зоны).
        x, y, z, rz, _kind, _spd_pct = args
        target = (
            self._decode(x, True),
            self._decode(y, True),
            self._decode(z, True),
            self._decode(rz, True),
        )
        self._active = {"target": target, "ticks_left": PTP_PLACEHOLDER_TICKS, "seq": seq}
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_PTP
        self.regs[REG["TLM_MOVING"]] = 1
        return ACK, 0, 0, []

    # --- прогресс активной длинной команды ---

    def _progress(self) -> None:
        if self._active is None:
            return
        self._active["ticks_left"] -= 1
        if self._active["ticks_left"] > 0:
            return
        x, y, z, rz = self._active["target"]
        seq = self._active["seq"]
        self.regs[REG["TLM_X"]] = self._encode(x, True)
        self.regs[REG["TLM_Y"]] = self._encode(y, True)
        self.regs[REG["TLM_Z"]] = self._encode(z, True)
        self.regs[REG["TLM_RZ"]] = self._encode(rz, True)
        self.regs[REG["TLM_ACTIVITY"]] = TLM_ACTIVITY_IDLE
        self.regs[REG["TLM_MOVING"]] = 0
        self._active = None
        self.regs[REG["TLM_DONE_SEQ"]] = seq  # И5: после ACTIVITY/MOVING/позы
