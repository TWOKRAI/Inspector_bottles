"""Слепые приёмочные тесты ``RobotClientV2`` против настоящего sim v2 (T3.1, RED до кода).

Стенд — настоящий ``SimRobotServer(core=RobotSimCoreV2())`` на свободном локальном порту и
настоящий ``ModbusDevice`` (TCP, ``unit_id=ROBOT_UNIT_ID``); подмен транспорта нет.
Журнал обмена — ``on_write`` сервера: он зовётся на КАЖДЫЙ доступ, в том числе на чтения
(``values=None``), поэтому «ноль записей» = нет вызовов с ``fc`` в {6, 16}.

Источник ожиданий — ``plans/robot-protocol-v2/protocol-spec.md`` §3–§8 и ``params.md``
§11.4, а не код sim и не код клиента: адреса, опкоды, errno здесь записаны литералами.
Сами тесты не читали ``client_v2.py`` (его ещё нет) и ``test_client_v2.py`` автора.

Что файл НЕ покрывает намеренно (пишет автор клиента): гонки, порядок записей внутри
транзакции, правила seq, таймауты и ретраи, ``stop(1)``/``stop(3)``, ``JOG_CONT``,
живой стенд (порт 5021 запрещён: см. ``_FORBIDDEN_PORTS``).
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.robot_comm.core.client_v2 import ClientV2Config, CmdResult, RobotClientV2, StopResult
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.errors import (
    RobotAborted,
    RobotCommandError,
    RobotNak,
    WrongFirmware,
)
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.server.sim_robot import SimRobotServer

# ---------------------------------------------------------------------------
# Литералы контракта (protocol-spec.md §3–§8, params.md §11.4)
# ---------------------------------------------------------------------------

_CMD_FLAG = 0x1000  # §3.1
_CMD_SEQ = 0x1001  # §3.1
_TLM_PROTO_VER = 0x1040  # §3.4
_TLM_ACTIVITY = 0x1043  # §3.4
_TLM_Y = 0x1045  # §3.4, s16 x0.1 мм
_TLM_DONE_SEQ = 0x1051  # §3.4
_TLM_ERRNO_LAST = 0x1053  # §3.4
_TLM_CFG_EPOCH = 0x105D  # §3.4

_PROTO_VER = 0x0200  # §3.4 / §5 PING: rvals = [PROTO_VER, FW_BUILD]
_OPCODE_PARAM_SET = 0x50  # §5
_ACTIVITY_PTP = 1  # §3.4
_E_RANGE = 3  # §6
_E_ABORTED = 13  # §6
_P_CONFIG_EPOCH_ID = 98  # params.md §11.3

# §5 PTP_MOVE: x, y, z, rz (s16 x0.1), kind (0 LINE), spd_pct. Дом = P_HOME_* = 300.0/-210.0/-40.0/-100.0.
_HOME_XYZRZ = [3000, -2100, -400, -1000]
_MOVE_SHORT = [3000, -2090, -400, -1000, 0, 100]  # 1 мм по Y на 100 % — завершается мгновенно
_MOVE_LONG = [3000, -1500, -400, -1000, 0, 1]  # 60 мм на 1 % — около 4 с (расчёт, не замер)
_MOVE_NAK = [*_HOME_XYZRZ, 0, 101]  # к дому, но spd_pct = 101 > 100 -> E_RANGE
_SHORT_Y_RAW = -2090

_FORBIDDEN_PORTS = frozenset({5021, 8765, 8766, 8091, 8092})
_WRITE_FCS = frozenset({6, 16})
_CALL_DEADLINE_S = 20.0  # потолок любого блокирующего вызова клиента в тестах
_STOP_BUDGET_S = 0.5  # п.6 приёмки: stop(2) при занятом mailbox

# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Копия из test_sim_e2e.py (копировать, не импортировать)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _checked_port() -> int:
    port = _free_port()
    assert port not in _FORBIDDEN_PORTS, f"порт {port} запрещён для тестов (живой стенд владельца)"
    return port


@dataclass(frozen=True, slots=True)
class MailboxCmd:
    """Команда mailbox, восстановленная по журналу: срез CMD_SEQ..ARGn в момент FC6 CMD_FLAG=1."""

    seq: int
    opcode: int
    argc: int
    args: list[int]


class Journal:
    """Потокобезопасный журнал ``on_write(fc, addr, values|None)`` сервера."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[tuple[int, int, list[int] | None]] = []

    def __call__(self, fc: int, addr: int, values: list[int] | None) -> None:
        with self._lock:
            self._calls.append((int(fc), int(addr), None if values is None else list(values)))

    def mark(self) -> int:
        with self._lock:
            return len(self._calls)

    def calls_since(self, mark: int = 0) -> list[tuple[int, int, list[int] | None]]:
        with self._lock:
            return list(self._calls[mark:])

    def writes_since(self, mark: int = 0) -> list[tuple[int, int, list[int] | None]]:
        return [c for c in self.calls_since(mark) if c[0] in _WRITE_FCS]

    def reads_since(self, mark: int = 0) -> list[tuple[int, int, list[int] | None]]:
        return [c for c in self.calls_since(mark) if c[0] not in _WRITE_FCS]

    def commands_since(self, mark: int = 0) -> list[MailboxCmd]:
        """Команды mailbox после ``mark``. Тень регистров строится с начала журнала, поэтому
        разбиение записи клиента на FC16/FC6 не важно: команда = срез на FC6 CMD_FLAG=1."""
        shadow: dict[int, int] = {}
        cmds: list[MailboxCmd] = []
        for index, (fc, addr, values) in enumerate(self.calls_since(0)):
            if values is None or fc not in _WRITE_FCS:
                continue
            for offset, value in enumerate(values):
                shadow[addr + offset] = value
            if fc == 6 and addr == _CMD_FLAG and values == [1] and index >= mark:
                argc = shadow.get(_CMD_SEQ + 2, 0)
                cmds.append(
                    MailboxCmd(
                        seq=shadow.get(_CMD_SEQ, 0),
                        opcode=shadow.get(_CMD_SEQ + 1, 0),
                        argc=argc,
                        args=[shadow.get(_CMD_SEQ + 3 + i, 0) for i in range(argc)],
                    )
                )
        return cmds


class Stand:
    """Настоящий sim + подключённый ``ModbusDevice`` + журнал + ленивый второй клиент-наблюдатель."""

    def __init__(self, core: RobotSimCore | RobotSimCoreV2) -> None:
        self.journal = Journal()
        self.port = _checked_port()
        self.server = SimRobotServer(
            host="127.0.0.1",
            port=self.port,
            unit_id=ROBOT_UNIT_ID,
            core=core,
            on_write=self.journal,
        )
        self._devices: list[ModbusDevice] = []
        self._observer: ModbusDevice | None = None
        self.server.start()
        self.transport = self._new_device()

    def _new_device(self) -> ModbusDevice:
        device = ModbusDevice(ModbusConfig(host="127.0.0.1", port=self.port, unit_id=ROBOT_UNIT_ID))
        self._devices.append(device)
        deadline = time.monotonic() + 5.0
        while not device.connect():
            assert time.monotonic() < deadline, "sim не принял соединение за 5 с"
            time.sleep(0.05)
        return device

    def observe(self, address: int) -> int:
        """Одно регистровое чтение вторым соединением (не мешает транспорту клиента)."""
        if self._observer is None:
            self._observer = self._new_device()
        return self._observer.read_holding(address, 1)[0]

    def make_client(self) -> RobotClientV2:
        config = ClientV2Config.from_dict(
            {
                "poll_interval_s": 0.01,
                "longest_gap_s": 2.0,
                "res_timeout_s": 2.0,
                "done_timeout_s": 15.0,
                "stop_echo_timeout_s": 2.0,
                "soft_echo_timeout_s": 2.0,
            }
        )
        return RobotClientV2(self.transport, config)

    def close(self) -> None:
        for device in self._devices:
            try:
                device.disconnect()
            except Exception:  # noqa: BLE001 — уборка: сбой закрытия не должен маскировать результат теста
                pass
        self.server.stop()


@pytest.fixture
def start_stand():
    """Фабрика стендов; все созданные закрываются по выходу из теста."""
    stands: list[Stand] = []

    def _start(core: RobotSimCore | RobotSimCoreV2 | None = None) -> Stand:
        stand = Stand(core if core is not None else RobotSimCoreV2())
        stands.append(stand)
        return stand

    yield _start
    for stand in reversed(stands):
        stand.close()


@pytest.fixture
def stand(start_stand) -> Stand:
    return start_stand()


@pytest.fixture
def client(stand: Stand) -> RobotClientV2:
    return stand.make_client()


# ---------------------------------------------------------------------------
# Блокирующий вызов в daemon-потоке с дедлайном join
# ---------------------------------------------------------------------------


class _Call:
    def __init__(self, fn, name: str) -> None:
        self._fn = fn
        self.name = name
        self.value = None
        self.exc: Exception | None = None
        self.elapsed: float | None = None
        self.done = threading.Event()
        self._thread = threading.Thread(target=self._body, name=name, daemon=True)

    def _body(self) -> None:
        t0 = time.monotonic()
        try:
            self.value = self._fn()
        except Exception as exc:  # noqa: BLE001 — исключение возвращается вызывающему потоку
            self.exc = exc
        finally:
            self.elapsed = time.monotonic() - t0
            self.done.set()

    def start(self) -> _Call:
        self._thread.start()
        return self

    def wait(self, deadline_s: float = _CALL_DEADLINE_S) -> _Call:
        if not self.done.wait(deadline_s):
            pytest.fail(f"зависание: {self.name} не вернулся за {deadline_s} с")
        return self

    def result(self, deadline_s: float = _CALL_DEADLINE_S):
        self.wait(deadline_s)
        if self.exc is not None:
            raise self.exc
        return self.value


def call_blocking(fn, name: str = "client-call", deadline_s: float = _CALL_DEADLINE_S):
    return _Call(fn, name).start().result(deadline_s)


def _s16(raw: int) -> int:
    return raw - 0x10000 if raw >= 0x8000 else raw


def _wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _start_long_move(stand: Stand, client: RobotClientV2) -> CmdResult:
    """Запустить длинный ход (ACK получен, ход идёт) и убедиться наблюдателем, что он идёт."""
    result = call_blocking(lambda: client.cmd("PTP_MOVE", _MOVE_LONG), "long-move-cmd")
    assert _wait_until(lambda: stand.observe(_TLM_ACTIVITY) == _ACTIVITY_PTP), "длинный ход не стартовал"
    return result


# ---------------------------------------------------------------------------
# 1. probe на пустом пространстве -> WrongFirmware без единой записи
# ---------------------------------------------------------------------------


def _core_v1() -> RobotSimCore:
    return RobotSimCore()


def _core_v2_proto_zeroed() -> RobotSimCoreV2:
    core = RobotSimCoreV2()
    core.regs[_TLM_PROTO_VER] = 0
    return core


_EMPTY_SPACE_CORES = pytest.mark.parametrize(
    "core_factory",
    [_core_v1, _core_v2_proto_zeroed],
    ids=["v1-core", "v2-core-proto-ver-zeroed"],
)


@_EMPTY_SPACE_CORES
def test_probe_on_empty_space_raises_wrong_firmware(start_stand, core_factory) -> None:
    """Доказывает: в 0x1040 лежит 0 (v1-ядро или обнулённый PROTO_VER) -> probe() даёт
    ``WrongFirmware`` (protocol-spec §3.4, params §11.4 п.3).

    НЕ доказывает: поведение при ином ненулевом PROTO_VER (например 0x0100), при обрыве
    связи во время probe и текст сообщения исключения.
    """
    stand = start_stand(core_factory())
    client = stand.make_client()

    with pytest.raises(WrongFirmware):
        call_blocking(client.probe, "probe")


@_EMPTY_SPACE_CORES
def test_probe_on_empty_space_writes_nothing(start_stand, core_factory) -> None:
    """Доказывает: probe() на пустом пространстве не сделал ни одного FC6/FC16 и вообще
    обращался к роботу (были чтения) — иначе «ноль записей» выполнен пустым вызовом.

    НЕ доказывает: что чтение было именно по 0x1040 (журнал не хранит число регистров
    чтения), и что нет записей ПОСЛЕ возврата probe (журнал смотрится сразу после вызова).
    """
    stand = start_stand(core_factory())
    client = stand.make_client()

    with pytest.raises(WrongFirmware):
        call_blocking(client.probe, "probe")

    assert stand.journal.writes_since() == []
    assert stand.journal.reads_since(), "probe не обратился к роботу — пустой вызов не доказывает отсутствие записей"


def test_probe_on_v2_sim_passes_without_writes(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: probe() на настоящем sim v2 (PROTO_VER = 0x0200) не бросает и остаётся
    «только чтениями» (protocol-spec §3.4: probe до любых записей).

    НЕ доказывает: возвращаемое значение probe (в брифе не определено), версию сборки FW_BUILD.
    """
    call_blocking(client.probe, "probe")

    assert stand.journal.writes_since() == []


# ---------------------------------------------------------------------------
# 2. ACK
# ---------------------------------------------------------------------------


def test_cmd_ping_returns_ack_with_proto_ver(client: RobotClientV2) -> None:
    """Доказывает: ``cmd("PING", [])`` -> ``CmdResult`` с seq в 1..65535 и rvals =
    [PROTO_VER=0x0200, FW_BUILD] (protocol-spec §5, RVALC = 2).

    НЕ доказывает: значение FW_BUILD (§3.4: CRC сборки — литерала нет), NAK-ветку,
    идемпотентность повтора seq, поведение при занятом mailbox.
    """
    result = call_blocking(lambda: client.cmd("PING", []), "ping")

    assert isinstance(result, CmdResult)
    assert 1 <= result.seq <= 65535
    assert len(result.rvals) == 2
    assert list(result.rvals)[0] == _PROTO_VER


# ---------------------------------------------------------------------------
# 3. NAK с текстом
# ---------------------------------------------------------------------------


def test_cmd_move_with_spd_pct_101_raises_nak_e_range_with_text(client: RobotClientV2) -> None:
    """Доказывает: ``PTP_MOVE`` к дому со ``spd_pct = 101`` -> ``RobotNak``; ``errno`` = 3
    (E_RANGE, protocol-spec §6); ``text`` — непустая строка без литерала ``None``.

    НЕ доказывает: конкретные слова текста (§6 «Текст для GUI» не зафиксирован клиентом),
    поля ``reason`` / ``index`` / ``rvals`` и другие errno (E_BUSY, E_NO_SERVO...).
    """
    with pytest.raises(RobotNak) as excinfo:
        call_blocking(lambda: client.cmd("PTP_MOVE", _MOVE_NAK), "nak-move")

    nak = excinfo.value
    assert nak.errno == _E_RANGE
    assert isinstance(nak.text, str)
    assert nak.text.strip() != ""
    assert "None" not in nak.text


def test_nak_does_not_move_robot(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: после NAK на ход робот остался в IDLE (TLM_ACTIVITY = 0, §3.4) —
    отказ реально не запустил движение.

    НЕ доказывает: что NAK пришёл ОТ ПРОШИВКИ, а не из проверки в клиенте до записи
    (см. ``test_nak_is_produced_by_robot_not_by_client_precheck``).
    """
    with pytest.raises(RobotNak):
        call_blocking(lambda: client.cmd("PTP_MOVE", _MOVE_NAK), "nak-move")

    assert stand.observe(_TLM_ACTIVITY) == 0


def test_nak_is_produced_by_robot_not_by_client_precheck(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: NAK получен через mailbox — в журнале есть FC6 CMD_FLAG = 1 и команда
    PTP_MOVE со spd_pct = 101 в аргументах; значит ответ дал робот.

    НЕ доказывает: порядок записей внутри транзакции (§4: FC16 данных, затем FC6 флага
    отдельным вызовом) — это тесты автора.
    """
    with pytest.raises(RobotNak):
        call_blocking(lambda: client.cmd("PTP_MOVE", _MOVE_NAK), "nak-move")

    sent = stand.journal.commands_since()
    assert [(c.opcode, c.argc, c.args[5]) for c in sent] == [(0x10, 6, 101)]


def test_nak_leaves_mailbox_usable(client: RobotClientV2) -> None:
    """Доказывает: после RobotNak клиент не залип — следующий ``PING`` проходит (§4 п.1:
    NAK тоже закрывает транзакцию).

    НЕ доказывает: ретраи после NAK и очистку errno (``CLEAR_ERR``).
    """
    with pytest.raises(RobotNak):
        call_blocking(lambda: client.cmd("PTP_MOVE", _MOVE_NAK), "nak-move")

    result = call_blocking(lambda: client.cmd("PING", []), "ping-after-nak")

    assert list(result.rvals)[0] == _PROTO_VER


# ---------------------------------------------------------------------------
# 4. wait_done: успех и ошибка
# ---------------------------------------------------------------------------


def test_wait_done_returns_after_short_move(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: после короткого ``PTP_MOVE`` ``wait_done(seq)`` возвращается без
    исключения, TLM_DONE_SEQ = seq и поза Y сдвинулась на целевое значение (-209.0 мм).

    НЕ доказывает: таймаут ``done_timeout_s``, ожидание длинной команды до конца
    (там стоп прерывает раньше), опкоды HOME/JOG_STEP/CVT_JOB/SC_RUN.
    """
    result = call_blocking(lambda: client.cmd("PTP_MOVE", _MOVE_SHORT), "short-move")

    call_blocking(lambda: client.wait_done(result.seq), "wait-done")

    assert stand.observe(_TLM_DONE_SEQ) == result.seq
    assert abs(_s16(stand.observe(_TLM_Y)) - _SHORT_Y_RAW) <= 2


def test_wait_done_raises_robot_aborted_when_hard_stop_from_other_thread(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: длинный ход + ``stop(2)`` из другого потока -> ``wait_done`` бросает
    ``RobotAborted`` (подкласс ``RobotCommandError``); робот зафиксировал E_ABORTED = 13
    в TLM_ERRNO_LAST (§8 п.4, п.6) и TLM_DONE_SEQ не равен seq прерванной команды.

    НЕ доказывает: стоп SOFT/HALT, авария E_MOTION_FAULT / E_WDG_TIMEOUT вместо стопа
    (общий ``RobotCommandError`` без Aborted), время реакции (см. тест п.6).
    """
    result = _start_long_move(stand, client)
    waiter = _Call(lambda: client.wait_done(result.seq), "wait-done-long").start()
    time.sleep(0.3)
    assert not waiter.done.is_set(), "ход завершился сам до стопа — тест ничего не доказывает"

    call_blocking(lambda: client.stop(2), "stop-hard")

    waiter.wait(5.0)
    assert isinstance(waiter.exc, RobotAborted)
    assert isinstance(waiter.exc, RobotCommandError)
    assert stand.observe(_TLM_ERRNO_LAST) == _E_ABORTED
    assert stand.observe(_TLM_DONE_SEQ) != result.seq


# ---------------------------------------------------------------------------
# 5. Синхронизация параметров по метке
# ---------------------------------------------------------------------------


def _all_param_values() -> dict[str, int]:
    """Сырые значения всех имён PARAM_ID, кроме P_CONFIG_EPOCH (вход, не ожидание)."""
    return {name: int(PARAMS[pid]["default"]) for name, pid in PARAM_ID.items() if name != "P_CONFIG_EPOCH"}


def _assert_full_sync_sent(stand: Stand, mark: int, values: dict[str, int], epoch: int) -> None:
    commands = stand.journal.commands_since(mark)
    assert commands, "после метки нет ни одной команды mailbox — параметры не отправлялись"
    param_sets = {c.args[0]: c.args[1] for c in commands if c.opcode == _OPCODE_PARAM_SET}
    expected = {PARAM_ID[name]: raw & 0xFFFF for name, raw in values.items()}
    expected[_P_CONFIG_EPOCH_ID] = epoch
    assert param_sets == expected
    last = commands[-1]
    assert (last.opcode, last.args) == (_OPCODE_PARAM_SET, [_P_CONFIG_EPOCH_ID, epoch])
    epoch_writes = [c for c in commands if c.opcode == _OPCODE_PARAM_SET and c.args[0] == _P_CONFIG_EPOCH_ID]
    assert len(epoch_writes) == 1, "метка должна быть записана ровно один раз и последней"


def test_sync_params_on_fresh_robot_sends_all_and_epoch_last(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: робот с меткой 0, ПК с меткой 1 -> отправлены PARAM_SET для всех параметров
    словаря (значения как переданы) и ПОСЛЕДНЯЯ команда mailbox — ``PARAM_SET [98, 1]``
    (params §11.4 п.3), TLM_CFG_EPOCH стал 1.

    НЕ доказывает: сверку зеркала PMIR после записи, PARAM_APPLY при TLM_CFG_PENDING = 1,
    поведение при NAK на отдельный параметр, смысл полей ``sent`` / ``applied`` отчёта.
    """
    values = _all_param_values()
    call_blocking(client.probe, "probe")

    report = call_blocking(lambda: client.sync_params(values, 1), "sync")

    assert report.epoch == 1
    _assert_full_sync_sent(stand, 0, values, 1)
    assert stand.observe(_TLM_CFG_EPOCH) == 1


def test_sync_params_with_same_epoch_writes_nothing(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: после первой синхронизации тот же ``epoch`` -> ни одного FC6/FC16
    (params §11.4 п.3: «Совпала метка — ничего не отправляется»); первая синхронизация
    при этом реально писала (иначе тест пуст).

    НЕ доказывает: ветку «метка совпала, но PMIR_DICT отличается» (отпечаток словаря),
    ветку «робот сбросил параметры» (п.4) и тихую рассинхронизацию значений при той же метке.
    """
    values = _all_param_values()
    call_blocking(client.probe, "probe")
    call_blocking(lambda: client.sync_params(values, 1), "sync-first")
    assert stand.journal.writes_since(), "первая синхронизация ничего не записала — предусловие нарушено"
    assert stand.observe(_TLM_CFG_EPOCH) == 1
    mark = stand.journal.mark()

    report = call_blocking(lambda: client.sync_params(values, 1), "sync-same-epoch")

    assert report.epoch == 1
    assert stand.journal.writes_since(mark) == []


def test_sync_params_with_new_epoch_sends_all_and_epoch_last(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: метка разошлась (робот на 1, ПК на 2) -> отправлены ВСЕ параметры заново,
    последняя запись mailbox — ``PARAM_SET [98, 2]`` по журналу ``on_write``,
    TLM_CFG_EPOCH стал 2.

    НЕ доказывает: что отправлены только изменившиеся значения (здесь значения те же —
    требование «все при расхождении метки»), порядок параметров между собой, повтор при сбое.
    """
    values = _all_param_values()
    call_blocking(client.probe, "probe")
    call_blocking(lambda: client.sync_params(values, 1), "sync-first")
    assert stand.observe(_TLM_CFG_EPOCH) == 1
    mark = stand.journal.mark()

    report = call_blocking(lambda: client.sync_params(values, 2), "sync-new-epoch")

    assert report.epoch == 2
    _assert_full_sync_sent(stand, mark, values, 2)
    assert stand.observe(_TLM_CFG_EPOCH) == 2


# ---------------------------------------------------------------------------
# 6. Стоп проходит, пока mailbox занят длинной командой
# ---------------------------------------------------------------------------


def test_hard_stop_acked_within_budget_while_long_move_waits(stand: Stand, client: RobotClientV2) -> None:
    """Доказывает: пока поток A в ``wait_done`` длинного хода (ACTIVITY = PTP), поток B
    ``stop(2)`` возвращает ``StopResult.ACKED`` не позже 0.5 с (§4 п.3, §8: стоп не зависит
    от задержки ответа mailbox), а A получает ``RobotAborted``.

    НЕ доказывает: стоп через сколь угодно долгий примитив на железе (sim не воспроизводит
    задержку Motion), ``StopResult.SUPERSEDED`` (второй стоп поверх первого), SOFT / HALT,
    стабильность 0.5 с на медленной машине (бюджет — из брифа, не измерен на CI).
    """
    result = _start_long_move(stand, client)
    waiter = _Call(lambda: client.wait_done(result.seq), "wait-done-long").start()
    time.sleep(0.3)
    assert not waiter.done.is_set(), "ход завершился сам до стопа — mailbox не был занят"
    assert stand.observe(_TLM_ACTIVITY) == _ACTIVITY_PTP

    stopper = _Call(lambda: client.stop(2), "stop-hard").start()
    stop_result = stopper.result(5.0)

    assert stopper.elapsed is not None
    assert stopper.elapsed <= _STOP_BUDGET_S, f"stop(2) занял {stopper.elapsed:.3f} с, бюджет {_STOP_BUDGET_S} с"
    assert stop_result is StopResult.ACKED
    waiter.wait(5.0)
    assert isinstance(waiter.exc, RobotAborted)
