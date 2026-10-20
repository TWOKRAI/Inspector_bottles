# -*- coding: utf-8 -*-
"""Task 0.2 (gui-graceful-close): ``BackendDriver.system_shutdown`` и MCP-инструмент ``system_shutdown``.

Приёмка вслепую (стадия 1). Контракт — ``plans/2026-10-20_gui-graceful-close/tasks/0.2.md``, DESIGN шаги 4–5:

  * ``system_shutdown(mode="graceful", deadline_s=1.0, wait=True, wait_timeout=20.0) -> dict``;
  * команда уходит через ``system_command`` со сроком запроса 6.0 с;
  * при ``wait`` драйвер опрашивает ``connection_lost`` каждые 100 мс до ``True`` или ``wait_timeout``;
  * возврат ``{"accepted": bool | None, "mode", "elapsed_s", "pm_gone", "outcomes": None}``;
    ``accepted=None``, если ответ на команду — timeout (сокет всё равно ждём);
    ``pm_gone`` = «PM закрыл сокет backend_ctl»;
  * MCP-инструмент ``system_shutdown`` зарегистрирован, класс безопасности ``escalated``.

Транспорт фейковый (по образцу ``test_restart_verified.py``): ``system_command`` подменён на экземпляре,
``connection_lost`` — свойство-счётчик в подклассе. Сокетов и процессов нет.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_tools import TOOL_SAFETY, TOOLS, build_registry

_CALL_DEADLINE_S = 15.0
_WAIT_TIMEOUT_S = 0.5


class _LossyDriver(BackendDriver):
    """Драйвер, чей ``connection_lost`` становится ``True`` с N-го чтения (``None`` — никогда)."""

    def __init__(self, lost_at_read: int | None) -> None:
        self._lost_at_read = lost_at_read
        self.reads = 0
        super().__init__()

    @property
    def connection_lost(self) -> bool:  # type: ignore[override]
        self.reads += 1
        return self._lost_at_read is not None and self.reads >= self._lost_at_read


def _bounded(fn: Callable[[], Any], deadline_s: float = _CALL_DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший драйвер валит тест, а не набор."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"system_shutdown завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _driver(monkeypatch: pytest.MonkeyPatch, *, lost_at_read: int | None, reply: dict) -> tuple[_LossyDriver, list]:
    drv = _LossyDriver(lost_at_read)
    sent: list[tuple[dict, float | None]] = []

    def fake_system_command(command: dict, *, timeout: float | None = None) -> dict:
        sent.append((command, timeout))
        return reply

    monkeypatch.setattr(drv, "system_command", fake_system_command)
    return drv, sent


@pytest.mark.parametrize(
    ("lost_at_read", "expect_gone"),
    [pytest.param(3, True, id="lost-on-3rd-poll"), pytest.param(None, False, id="never-lost")],
)
def test_wait_distinguishes_gone_from_timeout(
    monkeypatch: pytest.MonkeyPatch, lost_at_read: int | None, expect_gone: bool
) -> None:
    drv, sent = _driver(
        monkeypatch, lost_at_read=lost_at_read, reply={"success": True, "message": "Shutdown initiated"}
    )

    res = _bounded(lambda: drv.system_shutdown(mode="force", deadline_s=1.0, wait_timeout=_WAIT_TIMEOUT_S))

    assert res["pm_gone"] is expect_gone, res
    assert res["accepted"] is True, res
    assert res["mode"] == "force", res
    assert res["outcomes"] is None, res
    if expect_gone:
        assert res["elapsed_s"] < _WAIT_TIMEOUT_S, f"сокет закрылся на 3-м опросе, а ждали {res['elapsed_s']} с"
    else:
        assert _WAIT_TIMEOUT_S <= res["elapsed_s"] <= _WAIT_TIMEOUT_S + 1.0, res
    # Команда: одна, system.shutdown c заданными mode/deadline_s, срок запроса 6.0 с (предел (а) брифа).
    assert len(sent) == 1, sent
    command, timeout = sent[0]
    assert command["cmd"] == "system.shutdown"
    assert command["mode"] == "force"
    assert command["deadline_s"] == 1.0
    assert timeout == 6.0, timeout


def test_command_timeout_gives_accepted_none_and_still_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    drv, sent = _driver(
        monkeypatch,
        lost_at_read=3,
        reply={"success": False, "error": "timeout", "request_id": "r1"},
    )

    res = _bounded(lambda: drv.system_shutdown(mode="force", wait_timeout=_WAIT_TIMEOUT_S))

    assert res["accepted"] is None, f"timeout ответа != отказ: accepted должен быть None, получено {res}"
    # «Всё равно ждать закрытия сокета»: pm_gone=True достижим только если драйвер продолжил опрос.
    assert res["pm_gone"] is True, res
    assert drv.reads >= 3, f"connection_lost опрошен {drv.reads} раз — драйвер не ждал сокет"
    assert len(sent) == 1, sent


class _RecordingDriver:
    """Подставной драйвер для handler'а MCP-инструмента: сигнатура — из брифа (шаг 4)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def system_shutdown(
        self, mode: str = "graceful", deadline_s: float = 1.0, wait: bool = True, wait_timeout: float = 20.0
    ) -> dict:
        self.calls.append({"mode": mode, "deadline_s": deadline_s, "wait": wait, "wait_timeout": wait_timeout})
        return {"accepted": True, "mode": mode, "elapsed_s": 0.0, "pm_gone": True, "outcomes": None}


def test_mcp_tool_registered_as_escalated() -> None:
    registry = build_registry()
    assert "system_shutdown" in registry, "MCP-инструмент system_shutdown не зарегистрирован"
    assert "system_shutdown" in {spec.name for spec in TOOLS}
    assert TOOL_SAFETY.get("system_shutdown") == "escalated", TOOL_SAFETY.get("system_shutdown")

    spec = registry["system_shutdown"]
    properties = spec.input_schema.get("properties", {})
    assert "mode" in properties and "deadline_s" in properties, sorted(properties)

    # Эффект handler'а: аргументы инструмента доходят до метода драйвера.
    fake = _RecordingDriver()
    result = spec.handler(fake, {"mode": "force", "deadline_s": 2.0})
    assert len(fake.calls) == 1, fake.calls
    assert fake.calls[0]["mode"] == "force"
    assert fake.calls[0]["deadline_s"] == 2.0
    assert result["pm_gone"] is True, result
