"""Независимые приёмочные тесты симулятора v2 (T2.1), написанные ДО реализации.

Источник истины — приёмочный контракт (t2.1-contract.md), а не сам v1-симулятор:
адреса/опкоды/errno/ids параметров берутся по имени из
`Services.robot_comm.core.protocol_v2` и `Services.robot_comm.core.params_v2`,
но там, где контракт прямо называет число (PING rvals, PMIR_MAGIC, ACK/NAK) —
число записано литералом, а не выведено из кода под тестом.

Реализация `Services.robot_comm.server.sim_core_v2` ещё не существует — весь файл
красный на ModuleNotFoundError, это ожидаемое состояние (RED = спецификация для
разработчика). Не трогать: v1-симулятор (`sim_core.py`), опкоды HOME/JOG_*/CVT_JOB/
SC_RUN, SOFT-стоп во время движения, HB_PC/JOG_LEASE — вне рамок T2.1.
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.params_v2 import DICT_FINGERPRINT, PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ERR, KIND, OP, REG, REG_COUNT

# сгенерирован разработчиком по контракту T2.1; до этого момента файл целиком RED
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

# ACK/NAK и magic контракт прямо называет числом -> литерал, не импорт
ACK = 1
NAK = 2
PMIR_MAGIC_VALUE = 0x5632
PROTO_VER = 0x0200

FW_BUILD = 7


# --------------------------------------------------------------------------- #
# CRC16/MODBUS зеркала параметров — реализовано в тесте по тексту контракта,
# codegen НЕ импортируется.
# --------------------------------------------------------------------------- #


def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS: reflected poly 0xA001, init 0xFFFF, без final xor."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def test_crc16_modbus_known_vector():
    # каталожный check-value для CRC-16/MODBUS: вход b"123456789" -> 0x4B37.
    # Без этой проверки ошибка в моей же реализации CRC давала бы ложный
    # результат во всех тестах восстановления зеркала (и в плюс, и в минус).
    assert crc16_modbus(b"123456789") == 0x4B37


def mirror_crc(regs: list[int]) -> int:
    """CRC зеркала параметров: по возрастанию id, u16 little-endian, & 0x7FFF."""
    data = bytearray()
    for pid in sorted(PARAMS.keys()):
        raw = regs[REG["PMIR"] + pid] & 0xFFFF
        data += raw.to_bytes(2, "little")
    return crc16_modbus(bytes(data)) & 0x7FFF


def u16(value: int) -> int:
    return value & 0xFFFF


def decode(raw: int, signed: bool) -> int:
    if signed and raw >= 0x8000:
        return raw - 65536
    return raw


# --------------------------------------------------------------------------- #
# Регистр-помощники
# --------------------------------------------------------------------------- #


class RecordingRegs(list):
    """list, фиксирующий каждый __setitem__ (индекс или слайс) для теста И5."""

    def __init__(self, *args):
        super().__init__(*args)
        self.write_log: list[int] = []

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            self.write_log.extend(range(*key.indices(len(self))))
        else:
            idx = key + len(self) if key < 0 else key
            self.write_log.append(idx)
        super().__setitem__(key, value)


def last_pos(log: list[int], addr: int) -> int:
    positions = [i for i, a in enumerate(log) if a == addr]
    assert positions, f"адрес {addr:#06x} ни разу не записан в этом логе"
    return positions[-1]


def first_pos(log: list[int], addr: int) -> int:
    """Первая запись маркера: ПК видит маркер с момента ПЕРВОЙ записи, поэтому
    блок обязан быть дописан до неё (ранняя запись с последующей перезаписью —
    тот же дефект, что и перестановка)."""
    assert addr in log, f"адрес {addr:#06x} ни разу не записан в этом логе"
    return log.index(addr)


def cmd(core, seq: int, opcode: int, *args: int, argc: int | None = None) -> dict:
    """Пишет SEQ/OPCODE/ARGC/ARGS, затем CMD_FLAG=1 отдельной записью, тикает раз."""
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    n = len(args) if argc is None else argc
    core.write(REG["CMD_ARGC"], [n])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    return read_res(core)


def read_res(core) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    seq_written = core.read(REG["RES_SEQ"], 1)[0]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals, "seq": seq_written}


def home_target(dx: int = 0):
    x = PARAMS[PARAM_ID["P_HOME_X"]]["default"] + dx
    y = PARAMS[PARAM_ID["P_HOME_Y"]]["default"]
    z = PARAMS[PARAM_ID["P_HOME_Z"]]["default"]
    rz = PARAMS[PARAM_ID["P_HOME_RZ"]]["default"]
    return x, y, z, rz


def start_long_command(core, seq: int) -> dict:
    """SERVO on + PTP_MOVE JOINT в home+100мм по X — единственная длинная команда T2.1."""
    servo_res = cmd(core, seq, OP["SERVO"], 1)
    assert servo_res["status"] == ACK, "предусловие: серво должно включиться"
    x, y, z, rz = home_target(dx=1000)
    res = cmd(core, seq + 1, OP["PTP_MOVE"], x, y, z, rz, KIND["JOINT"], 50)
    assert res["status"] == ACK, "предусловие: PTP_MOVE из дома должен приниматься"
    return res


def run_until_idle(core, max_ticks: int = 500) -> int:
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick()
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def recording_core() -> RobotSimCoreV2:
    regs = RecordingRegs([0] * REG_SPACE_SIZE_V2)
    return RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)


# --------------------------------------------------------------------------- #
# Boot (пункт 5 частично + инфраструктура)
# --------------------------------------------------------------------------- #


def test_reg_space_size_covers_pmir_dict():
    assert REG_SPACE_SIZE_V2 > REG["PMIR_DICT"]


def test_init_default_allocates_reg_space_of_declared_size():
    core = fresh_core()
    assert len(core.regs) == REG_SPACE_SIZE_V2


def test_init_with_given_regs_uses_same_list_object():
    regs = [0] * REG_SPACE_SIZE_V2
    core = RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)
    assert core.regs is regs


def test_boot_sets_proto_ver_and_fw_build():
    core = fresh_core()
    assert core.read(REG["TLM_PROTO_VER"], 1)[0] == PROTO_VER
    assert core.read(REG["TLM_FW_BUILD"], 1)[0] == FW_BUILD


def test_boot_invalid_mirror_uses_all_defaults():
    core = fresh_core()  # regs=None -> всё в нулях -> magic невалиден
    for pid, meta in PARAMS.items():
        raw = core.read(REG["PMIR"] + pid, 1)[0]
        assert decode(raw, meta["signed"]) == meta["default"], meta["name"]


def test_boot_writes_valid_mirror_magic_dict_and_crc():
    core = fresh_core()
    assert core.read(REG["PMIR_MAGIC"], 1)[0] == PMIR_MAGIC_VALUE
    assert core.read(REG["PMIR_DICT"], 1)[0] == DICT_FINGERPRINT
    assert core.read(REG["PMIR_CRC"], 1)[0] == mirror_crc(core.regs)


def test_boot_default_pose_from_home_params():
    core = fresh_core()
    x, y, z, rz = home_target()
    assert core.read(REG["TLM_X"], 1)[0] == u16(x)
    assert core.read(REG["TLM_Y"], 1)[0] == u16(y)
    assert core.read(REG["TLM_Z"], 1)[0] == u16(z)
    assert core.read(REG["TLM_RZ"], 1)[0] == u16(rz)


def test_boot_initial_activity_servo_and_do_mask():
    core = fresh_core()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1
    assert core.read(REG["TLM_DO_MASK"], 1)[0] == 0


def test_boot_leftover_stop_req_is_echoed_but_not_reacted_to():
    # STOP_REQ=HALT(3) уже стоял до старта прошивки -> "уже обработан": эхо в
    # TLM_STOP_ACK есть, но серво (initial state = 1, "как в v1") boot не гасит.
    # NB: это моя трактовка неоднозначной фразы "already processed" — см. отчёт.
    regs = [0] * REG_SPACE_SIZE_V2
    regs[REG["STOP_REQ"]] = 3
    core = RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)
    for _ in range(3):  # реакция на стоп живёт в tick(), без тиков её не увидеть
        core.tick()
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 3
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1


# --------------------------------------------------------------------------- #
# Пункт 1: ACK/NAK по каждому опкоду таблицы
# --------------------------------------------------------------------------- #


def test_ping_returns_proto_ver_and_fw_build():
    core = fresh_core()
    res = cmd(core, 1, OP["PING"])
    assert res["status"] == ACK
    assert res["rvalc"] == 2
    assert res["rvals"] == [PROTO_VER, FW_BUILD]


def test_bad_opcode_is_nak():
    core = fresh_core()
    res = cmd(core, 1, 0x7F, argc=0)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BAD_OPCODE"]


def test_bad_argc_is_nak():
    core = fresh_core()
    res = cmd(core, 1, OP["PING"], argc=1)  # PING ждёт argc=0
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BAD_ARGC"]


def test_clear_err_resets_errno_and_err_seq_not_err_evt():
    core = fresh_core()
    start_long_command(core, seq=1)
    core.write(REG["STOP_REQ"], [2])  # HARD -> абортирует и взводит ERRNO_LAST/ERR_SEQ/ERR_EVT
    core.tick()
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    err_evt_before = core.read(REG["TLM_ERR_EVT"], 1)[0]
    res = cmd(core, 100, OP["CLEAR_ERR"])
    assert res["status"] == ACK
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == err_evt_before  # событие не откатывается


def test_servo_on_and_off_ack():
    core = fresh_core()
    res_off = cmd(core, 1, OP["SERVO"], 0)
    assert res_off["status"] == ACK
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0
    res_on = cmd(core, 2, OP["SERVO"], 1)
    assert res_on["status"] == ACK
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1


def test_servo_out_of_range_is_nak_and_unchanged():
    core = fresh_core()
    before = core.read(REG["TLM_SERVO"], 1)[0]
    res = cmd(core, 1, OP["SERVO"], 2)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert core.read(REG["TLM_SERVO"], 1)[0] == before


def test_do_set_ack_sets_correct_bit():
    core = fresh_core()
    res = cmd(core, 1, OP["DO_SET"], 3, 1)
    assert res["status"] == ACK
    mask = core.read(REG["TLM_DO_MASK"], 1)[0]
    assert mask & (1 << (3 - 1))


@pytest.mark.parametrize("channel", [0, 17])
def test_do_set_channel_out_of_range_is_nak(channel):
    core = fresh_core()
    before = core.read(REG["TLM_DO_MASK"], 1)[0]
    res = cmd(core, 1, OP["DO_SET"], channel, 1)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert core.read(REG["TLM_DO_MASK"], 1)[0] == before


def test_do_set_value_out_of_range_is_nak():
    core = fresh_core()
    before = core.read(REG["TLM_DO_MASK"], 1)[0]
    res = cmd(core, 1, OP["DO_SET"], 1, 2)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    assert core.read(REG["TLM_DO_MASK"], 1)[0] == before


def test_param_apply_ack_clears_pending():
    core = fresh_core()
    cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_BELT_FACTOR"], 2000)  # apply: reinit
    assert core.read(REG["TLM_CFG_PENDING"], 1)[0] == 1
    res = cmd(core, 2, OP["PARAM_APPLY"])
    assert res["status"] == ACK
    assert core.read(REG["TLM_CFG_PENDING"], 1)[0] == 0


def test_ack_seq_updates_on_ack_not_on_nak():
    core = fresh_core()
    ok = cmd(core, 7, OP["PING"])
    assert ok["status"] == ACK
    assert core.read(REG["TLM_ACK_SEQ"], 1)[0] == 7
    bad = cmd(core, 8, 0x7F, argc=0)
    assert bad["status"] == NAK
    assert core.read(REG["TLM_ACK_SEQ"], 1)[0] == 7  # не переехал на NAK-seq


# --------------------------------------------------------------------------- #
# Пункт 2: PARAM_SET / PARAM_GET, диапазоны, мёртвые id
# --------------------------------------------------------------------------- #


def test_param_get_unknown_id_is_bad_param():
    core = fresh_core()
    res = cmd(core, 1, OP["PARAM_GET"], 9999)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BAD_PARAM"]


def test_param_set_unknown_id_is_bad_param():
    core = fresh_core()
    res = cmd(core, 1, OP["PARAM_SET"], 9999, 1)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BAD_PARAM"]


def test_param_set_and_get_roundtrip_updates_mirror_and_crc():
    core = fresh_core()
    pid = PARAM_ID["P_SPD_DEFAULT"]  # apply: live, min1 max100
    res = cmd(core, 1, OP["PARAM_SET"], pid, 55)
    assert res["status"] == ACK
    got = cmd(core, 2, OP["PARAM_GET"], pid)
    assert got["status"] == ACK
    assert got["rvalc"] == 1
    assert got["rvals"][0] == 55
    assert core.read(REG["PMIR"] + pid, 1)[0] == 55
    assert core.read(REG["PMIR_CRC"], 1)[0] == mirror_crc(core.regs)


def test_param_set_out_of_range_keeps_value_and_mirror_untouched():
    core = fresh_core()
    pid = PARAM_ID["P_SPD_DEFAULT"]  # min 1, max 100, default 80
    crc_before = core.read(REG["PMIR_CRC"], 1)[0]
    mirror_before = core.read(REG["PMIR"] + pid, 1)[0]
    res = cmd(core, 1, OP["PARAM_SET"], pid, 101)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]
    got = cmd(core, 2, OP["PARAM_GET"], pid)
    assert got["rvals"][0] == 80
    assert core.read(REG["PMIR"] + pid, 1)[0] == mirror_before
    assert core.read(REG["PMIR_CRC"], 1)[0] == crc_before


def test_every_param_default_is_accepted():
    core = fresh_core()
    for pid, meta in PARAMS.items():
        res = cmd(core, pid + 1, OP["PARAM_SET"], pid, u16(meta["default"]))
        assert res["status"] == ACK, f"{meta['name']} default={meta['default']} должен приниматься"


def test_param_set_signed_min_minus_1_is_rejected():
    core = fresh_core()
    pid = PARAM_ID["P_WS_ANG_MIN"]  # signed, min=-1800, max=1800
    res = cmd(core, 1, OP["PARAM_SET"], pid, u16(-1801))
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_param_set_signed_max_plus_1_is_rejected():
    core = fresh_core()
    pid = PARAM_ID["P_WS_ANG_MAX"]  # signed, max=1800
    res = cmd(core, 1, OP["PARAM_SET"], pid, u16(1801))
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_param_set_unsigned_min_minus_1_is_rejected():
    core = fresh_core()
    pid = PARAM_ID["P_SPD_DEFAULT"]  # unsigned, min=1
    res = cmd(core, 1, OP["PARAM_SET"], pid, 0)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_param_set_unsigned_max_plus_1_is_rejected():
    core = fresh_core()
    pid = PARAM_ID["P_SPD_DEFAULT"]  # unsigned, max=100
    res = cmd(core, 1, OP["PARAM_SET"], pid, 101)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


def test_param_set_raw_0x8000_is_rejected_for_signed():
    core = fresh_core()
    pid = PARAM_ID["P_HOME_X"]  # signed, min=-32767
    res = cmd(core, 1, OP["PARAM_SET"], pid, 0x8000)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_RANGE"]


# --------------------------------------------------------------------------- #
# Пункт 3: busy-семантика во время длинной команды
# --------------------------------------------------------------------------- #


def test_live_param_accepted_during_long_command():
    core = fresh_core()
    start_long_command(core, seq=1)
    pid = PARAM_ID["P_SPD_DEFAULT"]  # apply: live
    res = cmd(core, 10, OP["PARAM_SET"], pid, 42)
    assert res["status"] == ACK
    got = cmd(core, 11, OP["PARAM_GET"], pid)
    assert got["rvals"][0] == 42


def test_idle_param_busy_during_long_command():
    core = fresh_core()
    start_long_command(core, seq=1)
    pid = PARAM_ID["P_SPD_L"]  # apply: idle
    before = cmd(core, 10, OP["PARAM_GET"], pid)["rvals"][0]
    res = cmd(core, 11, OP["PARAM_SET"], pid, 2000)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BUSY"]
    after = cmd(core, 12, OP["PARAM_GET"], pid)["rvals"][0]
    assert after == before


def test_reinit_param_busy_during_long_command():
    core = fresh_core()
    start_long_command(core, seq=1)
    pid = PARAM_ID["P_BELT_FACTOR"]  # apply: reinit
    before = cmd(core, 10, OP["PARAM_GET"], pid)["rvals"][0]
    res = cmd(core, 11, OP["PARAM_SET"], pid, 2000)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BUSY"]
    after = cmd(core, 12, OP["PARAM_GET"], pid)["rvals"][0]
    assert after == before


@pytest.mark.parametrize(
    "make_call",
    [
        lambda: (OP["SERVO"], (1,)),
        lambda: (OP["DO_SET"], (1, 1)),
        lambda: (OP["PARAM_APPLY"], ()),
    ],
)
def test_busy_deny_opcodes_nak_during_long_command(make_call):
    core = fresh_core()
    start_long_command(core, seq=1)
    opcode, args = make_call()
    res = cmd(core, 10, opcode, *args)
    assert res["status"] == NAK
    assert res["errno"] == ERR["E_BUSY"]


def test_ping_and_param_get_allowed_during_long_command():
    core = fresh_core()
    start_long_command(core, seq=1)
    ping = cmd(core, 10, OP["PING"])
    assert ping["status"] == ACK
    get = cmd(core, 11, OP["PARAM_GET"], PARAM_ID["P_SPD_DEFAULT"])
    assert get["status"] == ACK


# --------------------------------------------------------------------------- #
# Пункт 4: reinit -> CFG_PENDING до PARAM_APPLY
# --------------------------------------------------------------------------- #


def test_reinit_param_sets_cfg_pending_until_apply():
    core = fresh_core()
    assert core.read(REG["TLM_CFG_PENDING"], 1)[0] == 0
    res = cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_BELT_DIR"], 2)  # apply: reinit
    assert res["status"] == ACK
    assert core.read(REG["TLM_CFG_PENDING"], 1)[0] == 1
    apply_res = cmd(core, 2, OP["PARAM_APPLY"])
    assert apply_res["status"] == ACK
    assert core.read(REG["TLM_CFG_PENDING"], 1)[0] == 0


# --------------------------------------------------------------------------- #
# Пункт 5: рестарт и зеркало параметров
# --------------------------------------------------------------------------- #


def test_restart_with_valid_mirror_keeps_values_and_epoch():
    core = fresh_core()
    x_pid = PARAM_ID["P_HOME_X"]
    neg_pid = PARAM_ID["P_WS_ANG_MIN"]  # signed, отрицательный default/значение
    epoch_pid = PARAM_ID["P_CONFIG_EPOCH"]
    assert cmd(core, 1, OP["PARAM_SET"], x_pid, 1234)["status"] == ACK
    assert cmd(core, 2, OP["PARAM_SET"], neg_pid, u16(-500))["status"] == ACK
    assert cmd(core, 3, OP["PARAM_SET"], epoch_pid, 42)["status"] == ACK

    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)

    assert restarted.read(REG["PMIR"] + x_pid, 1)[0] == 1234
    assert restarted.read(REG["PMIR"] + neg_pid, 1)[0] == u16(-500)
    assert restarted.read(REG["TLM_CFG_EPOCH"], 1)[0] == 42
    assert restarted.read(REG["PMIR_CRC"], 1)[0] == mirror_crc(restarted.regs)


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda regs: regs.__setitem__(REG["PMIR_CRC"], u16(regs[REG["PMIR_CRC"]] + 1) & 0x7FFF),
        lambda regs: regs.__setitem__(REG["PMIR_MAGIC"], 0),
        lambda regs: regs.__setitem__(REG["PMIR_DICT"], DICT_FINGERPRINT + 1),
    ],
    ids=["bad_crc", "bad_magic", "bad_dict_fingerprint"],
)
def test_restart_with_corrupt_mirror_resets_all_defaults_and_epoch(corrupt):
    core = fresh_core()
    pid = PARAM_ID["P_SPD_DEFAULT"]
    epoch_pid = PARAM_ID["P_CONFIG_EPOCH"]
    assert cmd(core, 1, OP["PARAM_SET"], pid, 55)["status"] == ACK
    assert cmd(core, 2, OP["PARAM_SET"], epoch_pid, 42)["status"] == ACK

    corrupt(core.regs)
    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)

    assert restarted.read(REG["PMIR"] + pid, 1)[0] == PARAMS[pid]["default"]
    assert restarted.read(REG["TLM_CFG_EPOCH"], 1)[0] == 0
    assert restarted.read(REG["PMIR_MAGIC"], 1)[0] == PMIR_MAGIC_VALUE
    assert restarted.read(REG["PMIR_CRC"], 1)[0] == mirror_crc(restarted.regs)


def test_restart_single_out_of_range_slot_falls_back_only_that_param():
    core = fresh_core()
    keep_pid = PARAM_ID["P_SPD_DEFAULT"]
    broken_pid = PARAM_ID["P_ACC_L"]  # unsigned, min100 max50000
    assert cmd(core, 1, OP["PARAM_SET"], keep_pid, 55)["status"] == ACK
    assert cmd(core, 2, OP["PARAM_SET"], broken_pid, 12345)["status"] == ACK

    # смоделировать битую NVRAM: один слот зеркала испорчен вне диапазона,
    # но CRC пересчитан честно поверх испорченных данных (валиден как целое).
    core.regs[REG["PMIR"] + broken_pid] = 60000
    core.regs[REG["PMIR_CRC"]] = mirror_crc(core.regs)

    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)

    assert restarted.read(REG["PMIR"] + keep_pid, 1)[0] == 55
    assert restarted.read(REG["PMIR"] + broken_pid, 1)[0] == PARAMS[broken_pid]["default"]
    assert restarted.read(REG["PMIR_CRC"], 1)[0] == mirror_crc(restarted.regs)


# --------------------------------------------------------------------------- #
# Пункт 6: повтор seq — идемпотентность
# --------------------------------------------------------------------------- #


def test_repeated_seq_not_reexecuted_even_with_different_opcode():
    core = fresh_core()
    pid = PARAM_ID["P_SPD_DEFAULT"]
    first = cmd(core, 5, OP["PARAM_SET"], pid, 55)
    assert first["status"] == ACK
    # читаем напрямую регистр, а не через PARAM_GET-команду: любая новая команда
    # сама сдвинула бы "последний seq" и испортила бы проверку повтора seq=5 ниже
    assert core.read(REG["PMIR"] + pid, 1)[0] == 55

    # тот же seq=5, другой опкод (PING) -> не должен выполниться заново
    second = cmd(core, 5, OP["PING"])
    assert second["status"] == first["status"]
    assert second["errno"] == first["errno"]
    assert second["rvalc"] == first["rvalc"]
    assert second["rvals"] == first["rvals"]
    assert core.read(REG["PMIR"] + pid, 1)[0] == 55  # не перезаписано и не тронуто PING'ом


# --------------------------------------------------------------------------- #
# Пункт 7: плоскость STOP_REQ
# --------------------------------------------------------------------------- #


def test_stop_req_halt_in_idle_echoes_ack_and_kills_servo():
    core = fresh_core()
    core.write(REG["STOP_REQ"], [3])  # HALT
    core.tick()
    assert core.read(REG["TLM_STOP_ACK"], 1)[0] == 3
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0


def test_stop_req_repeated_value_does_not_act_twice():
    core = fresh_core()
    core.write(REG["STOP_REQ"], [3])  # HALT -> глушит серво
    core.tick()
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0
    # включаем серво заново штатной командой
    assert cmd(core, 1, OP["SERVO"], 1)["status"] == ACK
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1
    # STOP_REQ не менялся (то же значение 3) -> повторного действия быть не должно
    core.tick()
    core.tick()
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1


def test_stop_req_hard_aborts_long_command():
    core = fresh_core()
    move_res = start_long_command(core, seq=1)
    move_seq = move_res["seq"]
    core.write(REG["STOP_REQ"], [2])  # HARD
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == 0  # не завершение, а обрыв


def test_stop_req_halt_aborts_long_command_and_kills_servo():
    core = fresh_core()
    start_long_command(core, seq=1)
    core.write(REG["STOP_REQ"], [3])  # HALT
    core.tick()
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]


# --------------------------------------------------------------------------- #
# Placeholder-команда PTP_MOVE: тайминг (используется busy/STOP-тестами, но
# сама по себе тоже часть пункта 1 таблицы опкодов)
# --------------------------------------------------------------------------- #


def test_ptp_move_stays_active_for_at_least_3_ticks():
    core = fresh_core()
    start_long_command(core, seq=1)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0  # сразу после принятия
    for _ in range(3):  # ещё 3 тика ПОСЛЕ принятия — не должна завершиться раньше
        assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0
        core.tick()


def test_ptp_move_completes_within_500_ticks_at_target_pose():
    core = fresh_core()
    move_res = start_long_command(core, seq=1)
    run_until_idle(core, max_ticks=500)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    x, y, z, rz = home_target(dx=1000)
    assert core.read(REG["TLM_X"], 1)[0] == u16(x)
    assert core.read(REG["TLM_Y"], 1)[0] == u16(y)
    assert core.read(REG["TLM_Z"], 1)[0] == u16(z)
    assert core.read(REG["TLM_RZ"], 1)[0] == u16(rz)
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_res["seq"]


def test_unimplemented_opcodes_are_internal_error():
    # HOME/JOG_STEP/JOG_CONT реализованы в T2.2 (test_sim_v2_motion.py); здесь — только T2.3.
    core = fresh_core()
    for name, argc in (("CVT_JOB", 10), ("SC_RUN", 3)):
        res = cmd(core, 1, OP[name], *([0] * argc))
        assert res["status"] == NAK, name
        assert res["errno"] == ERR["E_INTERNAL"], name


# --------------------------------------------------------------------------- #
# Пункт 8: порядок записи (И5)
# --------------------------------------------------------------------------- #


def test_res_seq_written_last_on_ack():
    core = recording_core()
    core.regs.write_log.clear()
    cmd(core, 1, OP["PING"])
    log = core.regs.write_log
    seq_pos = first_pos(log, REG["RES_SEQ"])
    for addr in (REG["RES_STATUS"], REG["RES_ERRNO"], REG["RES_RVALC"]):
        assert last_pos(log, addr) < seq_pos


def test_res_seq_written_last_on_nak():
    core = recording_core()
    core.regs.write_log.clear()
    cmd(core, 1, 0x7F, argc=0)
    log = core.regs.write_log
    seq_pos = first_pos(log, REG["RES_SEQ"])
    for addr in (REG["RES_STATUS"], REG["RES_ERRNO"]):
        assert last_pos(log, addr) < seq_pos


def test_err_evt_written_after_err_seq_and_errno_last_on_abort():
    core = recording_core()
    start_long_command(core, seq=1)
    core.write(REG["STOP_REQ"], [2])  # HARD
    core.regs.write_log.clear()
    core.tick()
    log = core.regs.write_log
    evt_pos = first_pos(log, REG["TLM_ERR_EVT"])
    assert last_pos(log, REG["TLM_ERR_SEQ"]) < evt_pos
    assert last_pos(log, REG["TLM_ERRNO_LAST"]) < evt_pos


def test_done_seq_written_after_activity_and_moving_on_completion():
    core = recording_core()
    start_long_command(core, seq=1)
    log = None
    for _ in range(500):
        core.regs.write_log.clear()
        core.tick()
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            log = list(core.regs.write_log)
            break
    else:
        pytest.fail("команда не завершилась за 500 тиков")
    done_pos = first_pos(log, REG["TLM_DONE_SEQ"])
    assert last_pos(log, REG["TLM_ACTIVITY"]) < done_pos
    assert last_pos(log, REG["TLM_MOVING"]) < done_pos


def test_err_evt_written_after_servo_off_on_halt_abort():
    # Добавлено ведущим после инъекций T2.1: при HALT посреди команды серво
    # входит в блок события — ПК, увидев ERR_EVT, не должен прочитать SERVO=1.
    core = recording_core()
    start_long_command(core, seq=1)
    core.write(REG["STOP_REQ"], [3])  # HALT
    core.regs.write_log.clear()
    core.tick()
    log = core.regs.write_log
    assert last_pos(log, REG["TLM_SERVO"]) < first_pos(log, REG["TLM_ERR_EVT"])
