"""Независимые приёмочные тесты TCP-сервера sim v2 — `--protocol v2` (T2.3b).

Источник истины — protocol-spec.md §4 (хендшейк mailbox), §12 (PROBE до любых
записей) и design-брифа задачи: "server: `python -m Services.robot_comm.server
--protocol v2` serves RobotSimCoreV2 over Modbus TCP ... v1 stays the default".

Сегодня `Services/robot_comm/server/__main__.py` НЕ принимает `--protocol` —
флага нет вообще (проверено чтением файла, FILES этой задачи не включают
`__main__.py`/`sim_robot.py` — только чтение). Поэтому
`test_v2_server_ping_and_move_over_tcp` ожидаемо RED (процесс падает на
`argparse: unrecognized arguments` или зависает без ответа на порту — оба
случая ловятся с диагностикой, без зависания теста). `test_v1_server_still_default`
не использует `--protocol` вовсе (его как флага не существует) — GREEN уже
сегодня, это существующее поведение CLI.

ASSUMPTION (design: "if the name is unknown, test through CLI as subprocess"):
имя паблик-раннера v2 неизвестно -> тестируем ТОЛЬКО через CLI-поверхность
(`python -m Services.robot_comm.server --protocol v2 --port <port>`), не через
прямой импорт несуществующей функции.

Каждый блокирующий вызов — с дедлайном (poll-цикл, не `time.sleep`-ожидание
вслепую); subprocess всегда завершается в `finally` (terminate -> kill).
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import pytest

from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.core.protocol_v2 import CONSTANTS, OP, REG

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")

ACK = 1
NAK = 2
_READY_TIMEOUT_S = 5.0
_RES_TIMEOUT_S = 3.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _u16(v: int) -> int:
    return v & 0xFFFF


def _mm(eng: float) -> int:
    return round(eng * 10)


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.1)
        return s.connect_ex((host, port)) == 0


def _wait_ready(proc: subprocess.Popen, host: str, port: int, timeout: float = _READY_TIMEOUT_S) -> None:
    """Ждать порт ИЛИ смерть процесса — что раньше; без wall-clock-зависания теста."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            err = proc.stderr.read() if proc.stderr else ""
            pytest.fail(f"процесс сервера умер до готовности (код {proc.returncode}): stdout={out!r} stderr={err!r}")
        if _port_open(host, port):
            return
        time.sleep(0.02)
    proc.kill()
    pytest.fail(f"сервер не открыл порт {port} за {timeout}с")


@pytest.fixture
def v2_server():
    """Поднять `python -m Services.robot_comm.server --protocol v2 --port <free>` (CLI-поверхность,
    ASSUMPTION выше). Гарантированно завершается в finally."""
    host, port = "127.0.0.1", _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "Services.robot_comm.server", "--protocol", "v2", "--host", host, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_ready(proc, host, port)
        yield host, port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3.0)


def _write_cmd(client, seq: int, opcode: int, *args: int) -> None:
    values = [_u16(seq), opcode, len(args)] + [_u16(a) for a in args]
    client.write_registers(REG["CMD_SEQ"], values)
    client.write_register(REG["CMD_FLAG"], 1)


def _wait_res(client, seq: int, timeout: float = _RES_TIMEOUT_S) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.read_holding(REG["RES_SEQ"], 1)[0] == seq:
            status, errno, rvalc = client.read_holding(REG["RES_STATUS"], 3)
            rvals = client.read_holding(REG["RES_RVALS"], 8)[:rvalc]
            return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}
        time.sleep(0.02)
    pytest.fail(f"RES_SEQ не стал {seq} за {timeout}с")


def test_v2_server_ping_and_move_over_tcp(v2_server) -> None:
    """PING -> rvals[0] == PROTO_VER; PTP_MOVE реально двигает позу (не только ACK)."""
    from Services.modbus.core.config import ModbusConfig, TransportType
    from Services.robot_comm.core.registers import ROBOT_UNIT_ID
    from Services.modbus.sdk.client import ModbusSdkClient

    host, port = v2_server
    client = ModbusSdkClient(ModbusConfig(transport=TransportType.TCP, host=host, port=port, unit_id=ROBOT_UNIT_ID))
    assert client.connect()
    try:
        proto = client.read_holding(REG["TLM_PROTO_VER"], 1)[0]
        assert proto == CONSTANTS["PROTO_VER"]  # probe до любых записей (§12)

        _write_cmd(client, 1, OP["PING"])
        res = _wait_res(client, 1)
        assert res["status"] == ACK
        assert res["rvals"][0] == CONSTANTS["PROTO_VER"]

        home_x = client.read_holding(REG["TLM_X"], 1)[0]
        _write_cmd(client, 2, OP["PTP_MOVE"], _mm(200.0), _mm(0.0), _mm(-50.0), _mm(0.0), 2, 80)  # kind=JOINT
        res = _wait_res(client, 2)
        assert res["status"] == ACK, res

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and client.read_holding(REG["TLM_MOVING"], 1)[0] != 0:
            time.sleep(0.02)
        assert client.read_holding(REG["TLM_MOVING"], 1)[0] == 0, "PTP_MOVE не завершился за 10с"
        assert client.read_holding(REG["TLM_X"], 1)[0] != home_x, "поза не сдвинулась — PTP_MOVE не подействовал"
    finally:
        client.close()


def test_v1_server_still_default() -> None:
    """Без `--protocol` (флага, который ещё не существует) сервер — прежний v1.

    Существующее поведение CLI/`SimRobotServer` — GREEN уже сегодня."""
    host, port = "127.0.0.1", _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "Services.robot_comm.server", "--host", host, "--port", str(port), "--job-ms", "50"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_ready(proc, host, port)
        client = RobotClient(RobotConfig(host=host, port=port))
        assert client.connect()
        try:
            deadline = time.monotonic() + 3.0
            telemetry = None
            while time.monotonic() < deadline:
                telemetry = client.read_telemetry()
                if telemetry is not None:
                    break
                time.sleep(0.02)
            assert telemetry is not None, "v1-сервер не ответил телеметрией"
            assert telemetry.spd_pct == 50  # дефолт v1 sim-ядра (test_sim_e2e.py)
        finally:
            client.disconnect()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3.0)
