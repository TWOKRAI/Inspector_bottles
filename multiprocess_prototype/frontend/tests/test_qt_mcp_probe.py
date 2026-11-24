# -*- coding: utf-8 -*-
"""Опциональная проба qt-mcp: выключена по умолчанию, одна пара ручек QT_MCP_PROBE/QT_MCP_PORT, громкий отказ.

Две группы. Быстрые тесты с подменой ``installer`` проверяют ветвление ``install_if_enabled``. Подмена не доказывает,
что настоящий ``qt_mcp.probe.install`` ведёт себя так же, поэтому два теста внизу запускают настоящую пробу в
подпроцессе с offscreen-``QApplication`` (общий ``qapp`` pytest не трогаем). Проводку в ``app.py:run_gui`` (один
вызов ``install_if_enabled``) эти тесты НЕ доказывают: ``run_gui`` поднимает весь GUI-процесс.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from multiprocess_prototype.frontend.qt_mcp_probe import DEFAULT_PORT, install_if_enabled

REPO_ROOT = Path(__file__).resolve().parents[3]
ON = {"QT_MCP_PROBE": "1"}
_PROBE = object()  # метка «проба поставлена»: настоящая install возвращает объект Probe, не True


class _Installer:
    """Подмена ``qt_mcp.probe.install``: запоминает порты, возвращает метку (или то, что задали)."""

    def __init__(self, result: object = _PROBE, raises: Exception | None = None) -> None:
        self.calls: list[int] = []
        self._result = result
        self._raises = raises

    def __call__(self, *, port: int) -> object:
        self.calls.append(port)
        if self._raises is not None:
            raise self._raises
        return self._result


@pytest.mark.parametrize("env", [{}, {"QT_MCP_PROBE": ""}, {"QT_MCP_PROBE": "0"}])
def test_off_by_default_is_silent_and_does_not_call_installer(env: dict[str, str]) -> None:
    inst, lines = _Installer(), []

    assert install_if_enabled(env, warn=lines.append, installer=inst) is False

    assert inst.calls == []
    assert lines == []


def test_enabled_installs_on_default_port_and_says_open_door() -> None:
    inst, lines = _Installer(), []

    assert install_if_enabled(ON, warn=lines.append, installer=inst) is True

    assert DEFAULT_PORT == 9142
    assert inst.calls == [9142]
    assert len(lines) == 1
    assert lines[0].startswith("qt-mcp probe installed on localhost:9142")
    assert "без аутентификации" in lines[0]
    assert "127.0.0.1" in lines[0]


@pytest.mark.parametrize(("raw", "expected"), [("9150", 9150), (" 9150 ", 9150), ("1", 1), ("65535", 65535)])
def test_custom_port_is_passed(raw: str, expected: int) -> None:
    inst = _Installer()

    assert install_if_enabled({**ON, "QT_MCP_PORT": raw}, warn=lambda _m: None, installer=inst) is True

    assert inst.calls == [expected]


def test_empty_port_means_default() -> None:
    inst = _Installer()

    install_if_enabled({**ON, "QT_MCP_PORT": "  "}, warn=lambda _m: None, installer=inst)

    assert inst.calls == [9142]


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-5", "9142:1"])
def test_bad_port_warns_once_and_does_not_install_nor_fall_back(bad: str) -> None:
    """Битый порт не валит окно (нет исключения), не откатывается на 9142 (установщик не вызван), а кричит."""
    inst, lines = _Installer(), []

    assert install_if_enabled({**ON, "QT_MCP_PORT": bad}, warn=lines.append, installer=inst) is False

    assert inst.calls == []
    assert len(lines) == 1
    assert "QT_MCP_PORT" in lines[0]
    assert "1..65535" in lines[0]
    assert "проба не поставлена" in lines[0]


@pytest.mark.parametrize("typo", ["1:9142", "true", "yes", " 1", "2", "on"])
def test_flag_typo_warns_once_and_returns_false(typo: str) -> None:
    """Непустое значение, не равное «1» и «0», — опечатка: одно предупреждение, а не тишина."""
    inst, lines = _Installer(), []

    assert install_if_enabled({"QT_MCP_PROBE": typo}, warn=lines.append, installer=inst) is False

    assert inst.calls == []
    assert len(lines) == 1
    assert "QT_MCP_PROBE" in lines[0]
    assert "ожидается 1" in lines[0]


def test_install_returning_none_is_not_reported_as_installed() -> None:
    """Настоящий install вернёт None при занятом порте либо без QApplication: это отказ, а не успех."""
    inst, lines = _Installer(result=None), []

    assert install_if_enabled(ON, warn=lines.append, installer=inst) is False

    assert inst.calls == [9142]
    assert len(lines) == 1
    assert "не поставлена" in lines[0]
    assert "порт 9142 занят либо нет QApplication" in lines[0]
    assert "installed" not in lines[0]


def test_installer_exception_is_a_warning_not_a_crash() -> None:
    inst, lines = _Installer(raises=RuntimeError("boom-из-установки")), []

    assert install_if_enabled(ON, warn=lines.append, installer=inst) is False

    assert len(lines) == 1
    assert "boom-из-установки" in lines[0]
    assert "RuntimeError" in lines[0]


def test_missing_package_warns_and_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ручка включена, пакета нет (боевая сборка): не падение, а предупреждение; qt_mcp реально не импортируется."""
    monkeypatch.setitem(sys.modules, "qt_mcp", None)
    monkeypatch.setitem(sys.modules, "qt_mcp.probe", None)
    lines: list[str] = []

    assert install_if_enabled(ON, warn=lines.append) is False

    assert len(lines) == 1
    assert lines[0].startswith("qt-mcp: QT_MCP_PROBE=1, но пакет qt_mcp не установлен")


# --- настоящая проба в подпроцессе (offscreen QApplication, не общий qapp pytest) -------------------------------

_CHILD = textwrap.dedent(
    """
    import json, os, socket, sys, threading, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from multiprocess_prototype.frontend.qt_mcp_probe import install_if_enabled

    port = int(os.environ["QT_MCP_PORT"])
    warnings = []
    os.environ["QT_MCP_PROBE"] = "1"
    result = install_if_enabled(warn=warnings.append)

    pong = {}
    def ping():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                s.sendall(b'{"jsonrpc":"2.0","method":"ping","id":1}\\n')
                pong["raw"] = s.makefile("rb").readline().decode()
        except OSError as exc:
            pong["error"] = repr(exc)

    if result:
        t = threading.Thread(target=ping, daemon=True)
        t.start()
        deadline = time.monotonic() + 10
        while t.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    print(json.dumps({"result": result, "warnings": warnings, "pong": pong}))
    sys.stdout.flush()
    os._exit(0)
    """
)


def _run_child(port: int) -> dict:
    """Запустить настоящую пробу в отдельном процессе; жёсткий таймаут — зависание не вешает pytest."""
    pytest.importorskip("qt_mcp.probe")
    pytest.importorskip("PySide6.QtWidgets")
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_MCP_")}
    env.update({"QT_MCP_PORT": str(port), "PYTHONPATH": str(REPO_ROOT), "PYTHONUTF8": "1"})
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD], env=env, capture_output=True, text=True, timeout=90, cwd=REPO_ROOT
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_probe_answers_ping_on_custom_port() -> None:
    port = _free_port()  # не 9142: не мешаем живому стенду

    out = _run_child(port)

    assert out["result"] is True
    assert len(out["warnings"]) == 1
    assert out["warnings"][0].startswith(f"qt-mcp probe installed on localhost:{port}")
    assert json.loads(out["pong"]["raw"])["result"] == "pong"


def test_real_probe_on_busy_port_returns_false_with_one_warning() -> None:
    with socket.socket() as foreign:
        foreign.bind(("127.0.0.1", 0))
        foreign.listen(1)
        port = foreign.getsockname()[1]

        out = _run_child(port)

    assert out["result"] is False
    assert len(out["warnings"]) == 1
    assert f"порт {port} занят" in out["warnings"][0]
    assert "installed" not in out["warnings"][0]
