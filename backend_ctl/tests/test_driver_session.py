# -*- coding: utf-8 -*-
"""Тесты DriverSession — lifecycle-слой под MCP-сервером (A.4).

Проверяем два контракта readiness/устойчивости:
  * ensure(): ЛЮБОЕ исключение фабрики driver'а → BackendUnavailable, не сырое;
  * _await_ready(): неподтверждённая готовность PM → флаг _ready=False + warning +
    одноразовый маркер backend_warming в следующий tool-ответ (не тихий таймаут).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend_ctl.mcp_driver_session import BackendUnavailable, DriverSession


class _ProbeFakeDriver:
    """Fake с introspect_status — управляем исходом readiness-пробы."""

    def __init__(self, *, ready: bool) -> None:
        self._ready = ready
        self.calls = 0

    def introspect_status(self, process: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        self.calls += 1
        return {"success": True} if self._ready else {"success": False}


def _session(factory: Any) -> tuple[DriverSession, List[str]]:
    logs: List[str] = []
    return DriverSession(driver_factory=factory, log=logs.append), logs


# --- ensure(): любое исключение фабрики → BackendUnavailable ---


def test_factory_non_oserror_becomes_backend_unavailable() -> None:
    def _boom() -> Any:
        raise ValueError("сломанная фабрика")

    session, _ = _session(_boom)
    with pytest.raises(BackendUnavailable) as ei:
        session.ensure()
    # Не сырой ValueError, а понятный контракт с текстом и подсказкой BACKEND_CTL=1.
    assert "ValueError" in str(ei.value)
    assert "BACKEND_CTL=1" in str(ei.value)


def test_factory_oserror_becomes_backend_unavailable() -> None:
    def _no_socket() -> Any:
        raise OSError("connection refused")

    session, _ = _session(_no_socket)
    with pytest.raises(BackendUnavailable) as ei:
        session.ensure()
    assert "недоступен" in str(ei.value)


# --- _await_ready(): прогрев не молчит ---


def test_await_ready_timeout_sets_flag_warning_and_report() -> None:
    session, logs = _session(lambda: None)
    fake = _ProbeFakeDriver(ready=False)

    ok = session._await_ready(fake, attempts=1, probe_timeout=0.01)  # type: ignore[arg-type]

    assert ok is False
    assert session._ready is False
    assert any("readiness" in m for m in logs), "неподтверждённая готовность должна логировать warning"
    report = session.pop_reconnect_report()
    assert report is not None and report.get("backend_warming") is True
    # Отчёт одноразовый — второй pop уже пуст.
    assert session.pop_reconnect_report() is None


def test_await_ready_success_sets_ready_no_report() -> None:
    session, logs = _session(lambda: None)
    fake = _ProbeFakeDriver(ready=True)

    ok = session._await_ready(fake, attempts=3, probe_timeout=0.01)  # type: ignore[arg-type]

    assert ok is True
    assert session._ready is True
    assert fake.calls == 1, "успех на первой пробе — без лишних ретраев"
    assert session.pop_reconnect_report() is None
