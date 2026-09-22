# -*- coding: utf-8 -*-
"""Task 2.3b — независимый RED, живой стенд (тестер, worktree ДО реализации 2.3a/2.3b).

Гейт ``LINE_SIM_LIVE=1`` — тот же приём, что ``test_f2_task22_live.py`` (образец
фикстуры, скопирован почти дословно: ``BackendHarness`` на фиксированном порту
``_LINE_SIM_PORT=8766``, полный трёхпроцессный стенд, НИКОГДА не запускать по
умолчанию). Сегодня ``apps/line_sim/pipeline.yaml`` не содержит процесс ``pult``
(FILES п.5 задачи 2.3b — правка разработчика) и ``robot`` не знает команд
``belt.*`` (Task 2.3a) — по ЭТОЙ ЖЕ причине файл здесь только СОБИРАЕТСЯ
(``--collect-only``), не гоняется: живой сим владельца занимает порты
8766/5021/8091 прямо сейчас (TRAPS брифа), а до 2.3a/2.3b такой прогон и не
имел бы смысла (процесса ``pult`` нет).

Единственный тест файла — литерал из плана (Task 2.3b, REDS п.8): ``POST
/api/run {"freq_hz": 25}`` пульту -> ``backend_ctl`` видит тот же ``belt.status``
у ``robot`` (``mm_s`` 50.57 ± 0.5); ``POST /api/stop`` -> ``mm_s`` 0.0. Это тест
«настоящие объекты» (не двойник) — единственный в задаче, проверяющий, что
пульт РЕАЛЬНО дошёл до ``robot`` по IPC фреймворка, а не просто вызвал двойник.

Источники API: ``backend_ctl.harness.BackendHarness``,
``backend_ctl.driver.BackendDriver.send_command`` (см. образец
``apps/line_sim/tests/test_f1_task11_acceptance.py``, вызов ``drv.send_command
("robot", "sim_robot.status")``) — здесь адресуем новую команду ``belt.status``
(2.3a) той же парой «процесс, имя команды».

Догадка тестера: путь HTTP пульта ``POST http://127.0.0.1:8092/api/run`` и
JSON-тело ``{"freq_hz": 25}`` — из HTTP-таблицы DESIGN п.3 брифа 2.3b, не из
кода (кода пульта не существует)."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from backend_ctl.harness import BackendHarness

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("LINE_SIM_LIVE") != "1",
        reason="живой прогон полного стенда сима — только явно, LINE_SIM_LIVE=1",
    ),
    pytest.mark.timeout(120),
]

_APP_DIR = Path(__file__).resolve().parents[1]
_APP_YAML = _APP_DIR / "app.yaml"

_LINE_SIM_PORT = 8766  # литерал контракта (backend_ctl/tests/test_probe_acceptance_app_param.py)
_MODBUS_PORT = 5021
_MJPEG_PORT = 8091
_PULT_PORT = 8092  # литерал DESIGN п.1 брифа 2.3b


def _build_line_sim_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_APP_YAML)


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _assert_port_free(port: int) -> None:
    """8766/5021/8091/8092 — литералы контракта (TRAPS брифа 2.3b: не бегать от коллизии)."""
    with socket.socket() as probe:
        probe.settimeout(0.2)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            pytest.fail(f"порт {port} занят до старта теста — {exc}")


def _command_succeeded(res: Any) -> bool:
    if not isinstance(res, dict):
        return False
    if "success" in res:
        return bool(res.get("success"))
    return res.get("status") == "ok"


def _result_field(res: dict, key: str) -> Any:
    if key in res:
        return res[key]
    nested = res.get("result")
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return None


def _pult_post(path: str, body: dict, timeout: float = 5.0) -> dict:
    """POST JSON пульту (127.0.0.1:8092) — HTTP-таблица DESIGN п.3 брифа 2.3b."""
    url = f"http://127.0.0.1:{_PULT_PORT}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        pytest.fail(f"POST {path} -> HTTP {exc.code}: {exc.read()!r}")


@pytest.fixture
def line_sim_live_backend(tmp_path: Path):
    """Полный стенд ``apps/line_sim`` на фиксированных портах (форма — дословно
    ``test_f2_task22_live.py::line_sim_live_backend``, + порт пульта 8092)."""
    for port in (_LINE_SIM_PORT, _MODBUS_PORT, _MJPEG_PORT, _PULT_PORT):
        _assert_port_free(port)

    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    harness = BackendHarness(launcher_factory=_build_line_sim_launcher, port=_LINE_SIM_PORT)
    drv = harness.start()
    try:
        yield harness, drv
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log
        for port in (_LINE_SIM_PORT, _MODBUS_PORT, _MJPEG_PORT, _PULT_PORT):
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _port_is_open("127.0.0.1", port, timeout=0.3):
                time.sleep(0.2)
            assert not _port_is_open("127.0.0.1", port, timeout=0.3), (
                f"порт {port} всё ещё принимает соединения после harness.stop() — осиротевший процесс"
            )


def test_pult_drives_belt_end_to_end(line_sim_live_backend) -> None:
    """Пин (REDS п.8 брифа 2.3b): пульт реально форвардит команду ленты по IPC.

    ``POST /api/run {"freq_hz": 25}`` пульту -> ``backend_ctl`` тем же
    ``belt.status`` у ``robot`` видит ``mm_s`` 50.57 ± 0.5 (литерал плана,
    калибровка по умолчанию ``BeltDrive.from_enc_rate(7, 0.01)``); ``POST
    /api/stop`` -> ``mm_s`` 0.0."""
    _harness, drv = line_sim_live_backend

    _pult_post("/api/run", {"freq_hz": 25, "reverse": False})
    time.sleep(0.3)  # дать тикеру ленты применить команду (тот же зазор, что test_f2_task22_live)

    res = drv.send_command("robot", "belt.status", timeout=5.0)
    assert _command_succeeded(res), f"belt.status после /api/run не удался: {res!r}"
    mm_s = _result_field(res, "mm_s")
    assert mm_s == pytest.approx(50.57, abs=0.5), f"mm_s после /api/run 25 Гц: {mm_s!r} (ожидали 50.57 ± 0.5)"

    _pult_post("/api/stop", {})
    time.sleep(0.3)

    res2 = drv.send_command("robot", "belt.status", timeout=5.0)
    assert _command_succeeded(res2), f"belt.status после /api/stop не удался: {res2!r}"
    mm_s2 = _result_field(res2, "mm_s")
    assert mm_s2 == pytest.approx(0.0, abs=1e-6), f"mm_s после /api/stop: {mm_s2!r} (ожидали 0.0)"
