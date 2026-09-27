"""Тесты автора на внутренние опасности механизма RobotSimCoreV2 (T2.1).

Дополняют независимые приёмочные тесты `test_sim_v2_core.py` — те написаны
с внешней точки зрения (по контракту), эти — с точки зрения автора,
знающего реализацию: что может сломаться именно в ЭТОЙ механике (per-instance
состояние, порядок обработчиков внутри tick(), восстановление last_seq из
регистров при рестарте).
"""

from __future__ import annotations

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import OP, REG
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

ACK = 1
FW_BUILD = 7


def u16(value: int) -> int:
    return value & 0xFFFF


def cmd(core, seq, opcode, *args, argc=None):
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args) if argc is None else argc])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    return {
        "status": core.read(REG["RES_STATUS"], 1)[0],
        "errno": core.read(REG["RES_ERRNO"], 1)[0],
        "seq": core.read(REG["RES_SEQ"], 1)[0],
    }


def test_restart_then_retry_of_last_seq_is_not_reexecuted():
    """Ломается, если _last_seq после рестарта не восстанавливается из RES_SEQ:

    ПК не увидел ответ на seq=5 (например, обрыв связи), процесс перезапустился
    (regs выжили), ПК ретраит тот же seq=5 с ДРУГИМ opcode. Если ядро не помнит
    seq=5 как уже исполненный, PARAM_SET выполнится второй раз — тихая
    двойная запись параметра поверх того, что ПК уже считает подтверждённым.
    """
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    pid = PARAM_ID["P_SPD_DEFAULT"]
    first = cmd(core, 5, OP["PARAM_SET"], pid, 55)
    assert first["status"] == ACK
    assert core.read(REG["PMIR"] + pid, 1)[0] == 55

    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)
    # тот же seq=5, другое значение -> не должно исполниться заново
    retry = cmd(restarted, 5, OP["PARAM_SET"], pid, 77)
    assert retry["seq"] == 5
    assert restarted.read(REG["PMIR"] + pid, 1)[0] == 55  # повтор не записал 77


def test_stop_req_processed_before_mailbox_in_same_tick():
    """Ломается, если порядок внутри tick() перепутан (mailbox раньше стопа):

    ПК одним и тем же тиком просит и HARD-стоп активной команды, и SERVO(1).
    По контракту стоп обрабатывается ПЕРВЫМ — к моменту mailbox робот уже
    IDLE, поэтому SERVO (busy: deny) должен пройти. Если бы порядок был
    обратным, SERVO получил бы E_BUSY, потому что ACTIVITY ещё не сброшен.
    """
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    assert cmd(core, 1, OP["SERVO"], 1)["status"] == ACK
    x, y, z, rz = (
        core.read(REG["TLM_X"], 1)[0],
        core.read(REG["TLM_Y"], 1)[0],
        core.read(REG["TLM_Z"], 1)[0],
        core.read(REG["TLM_RZ"], 1)[0],
    )
    # +100 мм по X: с T2.2 ход в ту же позу завершается на ACK-тике, а нужна команда в полёте.
    assert cmd(core, 2, OP["PTP_MOVE"], x + 1000, y, z, rz, 2, 50)["status"] == ACK
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0

    # HARD-стоп и новая команда SERVO в ОДНОМ тике (без промежуточного tick()).
    core.write(REG["STOP_REQ"], [2])
    core.write(REG["CMD_SEQ"], [u16(3)])
    core.write(REG["CMD_OPCODE"], [OP["SERVO"]])
    core.write(REG["CMD_ARGC"], [1])
    core.write(REG["CMD_ARGS"], [0])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0  # стоп уже отработал
    assert core.read(REG["RES_STATUS"], 1)[0] == ACK  # SERVO прошёл, не E_BUSY


def test_hb_robot_wraps_at_16_bits():
    """Ломается на переполнении инкремента без маски & 0xFFFF: TLM_HB_ROBOT

    ушёл бы за 65535 и стал бы значением, которое ПК не отличит от честного
    маленького счётчика после долгого аптайма (u16-регистр не может хранить
    большее число молча — переполнение обязано оборачиваться, а не расти).
    """
    regs = [0] * REG_SPACE_SIZE_V2
    regs[REG["TLM_HB_ROBOT"]] = 0xFFFF
    core = RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)
    core.tick()
    assert core.read(REG["TLM_HB_ROBOT"], 1)[0] == 0


def test_attach_preserves_state_and_future_writes_land_in_new_list():
    """Ломается, если attach() не копирует состояние или продолжает писать

    в СТАРЫЙ список: TCP-сервер после attach() читал бы регистры из живого
    списка, который ядро больше не трогает — телеметрия виснет на старых
    значениях, хотя команды продолжают "успешно" исполняться.
    """
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    assert cmd(core, 1, OP["SERVO"], 0)["status"] == ACK
    assert core.read(REG["TLM_SERVO"], 1)[0] == 0

    new_regs = list(core.regs)
    core.attach(new_regs)
    assert core.regs is new_regs
    assert new_regs[REG["TLM_SERVO"]] == 0  # состояние скопировано

    assert cmd(core, 2, OP["SERVO"], 1)["status"] == ACK
    assert new_regs[REG["TLM_SERVO"]] == 1  # новые записи идут в new_regs


def test_two_instances_do_not_share_parameter_state():
    """Ломается при случайном модульном/классовом изменяемом состоянии

    (словарь значений параметров объявлен на уровне класса, а не в __init__):
    два одновременных робота на одном ПК начали бы делить настройки — смена
    override на одном роботе тихо поменяла бы скорость у другого.
    """
    core1 = RobotSimCoreV2(fw_build=FW_BUILD)
    core2 = RobotSimCoreV2(fw_build=FW_BUILD)
    pid = PARAM_ID["P_SPD_DEFAULT"]
    default = core2.read(REG["PMIR"] + pid, 1)[0]

    assert cmd(core1, 1, OP["PARAM_SET"], pid, 42)["status"] == ACK

    assert core1.read(REG["PMIR"] + pid, 1)[0] == 42
    # PARAM_GET, а не регистры: регистры у экземпляров свои всегда, общим
    # может оказаться только словарь значений внутри ядра.
    assert cmd(core2, 1, OP["PARAM_GET"], pid)["status"] == ACK
    assert core2.read(REG["RES_RVALS"], 1)[0] == default


def test_param_set_signed_raw_0xffff_decodes_to_minus_one():
    """Ломается при знаковом декодировании через int16 half-открытый диапазон

    или off-by-one в границе 0x8000: raw=0xFFFF обязан читаться как -1, а не
    как большое положительное число — иначе PARAM_SET валидного отрицательного
    значения (в пределах min..max) ошибочно улетит в E_RANGE или примет
    неверную величину.
    """
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    pid = PARAM_ID["P_HOME_X"]  # signed, min=-32767, max=32767 -> -1 валиден
    res = cmd(core, 1, OP["PARAM_SET"], pid, 0xFFFF)
    assert res["status"] == ACK
    got = cmd(core, 2, OP["PARAM_GET"], pid)
    assert got["status"] == ACK
    assert core.read(REG["RES_RVALS"], 1)[0] == 0xFFFF


def test_restart_mid_move_clears_moving():
    """Ломается, если загрузка не сбрасывает TLM_MOVING (ревью T2.1, п.1):

    рестарт программы посреди PTP_MOVE — команды больше нет, ACTIVITY=IDLE,
    а MOVING=1 остался бы навсегда и GUI показывал бы «едет» без движения.
    """
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    assert cmd(core, 7, OP["PTP_MOVE"], 4000, u16(-2100), u16(-400), u16(-1000), 2, 0)["status"] == ACK
    assert core.read(REG["TLM_MOVING"], 1)[0] == 1
    restarted = RobotSimCoreV2(regs=core.regs, fw_build=FW_BUILD)
    assert restarted.read(REG["TLM_MOVING"], 1)[0] == 0


def test_restart_with_garbage_rvalc_does_not_clobber_safety_plane():
    """Ломается без ограничения RES_RVALC при восстановлении ответа (ревью T2.1, п.2):

    мусор RES_RVALC=20 в регистрах к рестарту + повтор seq -> ответ переписал
    бы 20 слов от RES_RVALS, т.е. и STOP_REQ/HB_PC за блоком RES — ПК потерял бы
    свой свежий стоп, а старый обработался бы повторно.
    """
    regs = [0] * REG_SPACE_SIZE_V2
    regs[REG["RES_SEQ"]] = 3
    regs[REG["RES_STATUS"]] = ACK
    regs[REG["RES_RVALC"]] = 20
    core = RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)
    core.write(REG["STOP_REQ"], [43])
    core.write(REG["HB_PC"], [500])
    cmd(core, 3, OP["PING"])  # повтор последнего seq
    assert core.read(REG["STOP_REQ"], 1)[0] == 43
    assert core.read(REG["HB_PC"], 1)[0] == 500
