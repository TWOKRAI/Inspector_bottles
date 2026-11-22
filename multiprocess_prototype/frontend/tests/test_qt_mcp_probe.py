# -*- coding: utf-8 -*-
"""Опциональная проба qt-mcp: выключена по умолчанию, включается env-ручкой, не валит приложение без пакета."""

from __future__ import annotations

import sys

import pytest

from multiprocess_prototype.frontend.qt_mcp_probe import DEFAULT_PORT, install_if_enabled


class _Installer:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, *, port: int) -> None:
        self.calls.append(port)


def test_off_by_default_does_not_call_installer() -> None:
    inst = _Installer()

    assert install_if_enabled({}, installer=inst) is False
    assert install_if_enabled({"INSPECTOR_QT_MCP_PROBE": "0"}, installer=inst) is False
    assert inst.calls == []


def test_enabled_installs_on_default_port_and_logs() -> None:
    inst, lines = _Installer(), []

    assert install_if_enabled({"INSPECTOR_QT_MCP_PROBE": "1"}, log=lines.append, installer=inst) is True

    assert inst.calls == [9142]
    assert DEFAULT_PORT == 9142
    assert lines == ["qt-mcp: проба поставлена, 127.0.0.1:9142"]


def test_custom_port_is_passed() -> None:
    inst = _Installer()

    install_if_enabled({"INSPECTOR_QT_MCP_PROBE": "1", "INSPECTOR_QT_MCP_PORT": "9150"}, installer=inst)

    assert inst.calls == [9150]


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-5"])
def test_bad_port_is_an_error_not_a_silent_default(bad: str) -> None:
    inst = _Installer()

    with pytest.raises(ValueError, match="INSPECTOR_QT_MCP_PORT"):
        install_if_enabled({"INSPECTOR_QT_MCP_PROBE": "1", "INSPECTOR_QT_MCP_PORT": bad}, installer=inst)

    assert inst.calls == []


def test_missing_package_warns_and_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ручка включена, пакета нет (боевая сборка): не падение, а предупреждение; qt_mcp реально не импортируется."""
    monkeypatch.setitem(sys.modules, "qt_mcp", None)
    monkeypatch.setitem(sys.modules, "qt_mcp.probe", None)
    lines: list[str] = []

    assert install_if_enabled({"INSPECTOR_QT_MCP_PROBE": "1"}, log=lines.append) is False

    assert len(lines) == 1
    assert lines[0].startswith("qt-mcp: INSPECTOR_QT_MCP_PROBE=1, но пакет qt_mcp не установлен")
