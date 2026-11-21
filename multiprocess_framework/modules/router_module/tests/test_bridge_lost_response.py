# -*- coding: utf-8 -*-
"""Task 0.5b: мост порта не засчитывает отказ роутера как доставку.

``SocketBridgeAdapter.on_inbound`` отправляет ответ driver'у через
``router.send(response)``. ``_do_send`` роутера почти не бросает: основной путь
потери ответа — ответ-словарь ``{"status": "error", ...}`` (сессия ушла), а не
исключение. До 0.5b адаптер считал потерянным только исключение, и ответ
``error`` проходил как доставленный: ``lost_responses`` оставался нулём.

Каждый сценарий идёт в daemon-потоке с ``join(5)``: зависший адаптер — красный
тест, а не зависший прогон.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from ..adapters import socket_bridge_adapter as bridge_module
from ..adapters.socket_bridge_adapter import SocketBridgeAdapter

_JOIN_DEADLINE_S = 5.0

_SESSION_GONE = {"status": "error", "reason": "session not connected"}

# Полезная нагрузка ответа driver'у: в ERROR-лог она попадать не должна (b3).
_PAYLOAD_MARKER = "PAYLOAD-MARKER-7f3a"


class _ScriptedRouter:
    """Фейк роутера: ``request`` отдаёт результат, ``send`` — заданный ответ или исключение."""

    def __init__(
        self, send_result: Any = None, send_raises: bool = False, raise_text: str = "router send failed"
    ) -> None:
        self._send_result = send_result
        self._send_raises = send_raises
        self._raise_text = raise_text
        self.sent: List[Dict[str, Any]] = []

    def request(self, msg: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        return {"success": True, "data": {"secret": _PAYLOAD_MARKER}}

    def send(self, msg: Dict[str, Any]) -> Any:
        self.sent.append(msg)
        if self._send_raises:
            raise RuntimeError(self._raise_text)
        return self._send_result


class _CapturingLogger:
    """Подменяет модульный ``_logger`` адаптера: копит отформатированные ERROR-строки."""

    def __init__(self) -> None:
        self.errors: List[str] = []

    def error(self, msg: str, *args: Any) -> None:
        self.errors.append(msg % args if args else msg)

    def warning(self, msg: str, *args: Any) -> None:  # pragma: no cover - не ожидается
        self.errors.append("WARNING " + (msg % args if args else msg))


def _msg(request_id: str = "corr-1") -> Dict[str, Any]:
    return {
        "type": "command",
        "command": "introspect.handlers",
        "sender": "backend_ctl",
        "targets": ["preprocessor"],
        "data": {},
        "request_id": request_id,
    }


def _run_bounded(fn) -> Any:
    """Вызов в daemon-потоке с дедлайном; исключение потока пробрасывается."""
    box: Dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросить в поток теста
            box["error"] = exc

    thread = threading.Thread(target=target, name="bridge-probe", daemon=True)
    thread.start()
    thread.join(_JOIN_DEADLINE_S)
    assert not thread.is_alive(), f"on_inbound завис дольше {_JOIN_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def test_session_gone_counts_lost() -> None:
    """Ответ роутера ``error`` (сессия ушла) — потерянный ответ, а не доставка."""
    adapter = SocketBridgeAdapter(_ScriptedRouter(send_result=dict(_SESSION_GONE)), "backend_ctl")

    returned = _run_bounded(lambda: adapter.on_inbound(_msg()))

    assert returned is None
    assert adapter.get_stats()["lost_responses"] == 1


def test_dropped_response_counts_lost() -> None:
    """``dropped`` (исход ``refused``) у моста — тот же счётчик ``lost_responses``."""
    adapter = SocketBridgeAdapter(_ScriptedRouter(send_result={"status": "dropped", "reason": "full"}), "backend_ctl")

    _run_bounded(lambda: adapter.on_inbound(_msg()))

    assert adapter.get_stats()["lost_responses"] == 1


def test_exception_and_error_reply_share_one_counter() -> None:
    """Исключение ``send`` и ответ ``error`` считаются в один и тот же счётчик."""
    raising = _ScriptedRouter(send_raises=True)
    adapter = SocketBridgeAdapter(raising, "backend_ctl")

    _run_bounded(lambda: adapter.on_inbound(_msg("corr-1")))
    adapter._router = _ScriptedRouter(send_result=dict(_SESSION_GONE))
    _run_bounded(lambda: adapter.on_inbound(_msg("corr-2")))

    assert adapter.get_stats()["lost_responses"] == 2


def test_healthy_send_is_not_lost() -> None:
    """Здоровый ответ (``success``, ``None``) не растит ``lost_responses``."""
    adapter = SocketBridgeAdapter(_ScriptedRouter(send_result={"status": "success"}), "backend_ctl")
    _run_bounded(lambda: adapter.on_inbound(_msg("corr-1")))
    adapter._router = _ScriptedRouter(send_result=None)
    _run_bounded(lambda: adapter.on_inbound(_msg("corr-2")))

    assert adapter.get_stats()["lost_responses"] == 0


def test_lost_log_names_reason_not_payload(monkeypatch) -> None:
    """ERROR-лог несёт причину, ``request_id`` и канал — но не полезную нагрузку ответа."""
    captured = _CapturingLogger()
    monkeypatch.setattr(bridge_module, "_logger", captured)
    session_gone = dict(_SESSION_GONE)
    session_gone["echo"] = {"result": {"secret": _PAYLOAD_MARKER}}
    adapter = SocketBridgeAdapter(_ScriptedRouter(send_result=session_gone), "backend_ctl")

    _run_bounded(lambda: adapter.on_inbound(_msg("corr-42")))

    assert len(captured.errors) == 1, captured.errors
    line = captured.errors[0]
    assert "session not connected" in line
    assert "corr-42" in line
    assert "backend_ctl" in line
    assert _PAYLOAD_MARKER not in line


def test_send_exception_log_names_class_not_text(monkeypatch) -> None:
    """Исключение ``send``: в лог идёт имя класса, текст исключения (значения ответа) — нет."""
    captured = _CapturingLogger()
    monkeypatch.setattr(bridge_module, "_logger", captured)
    adapter = SocketBridgeAdapter(_ScriptedRouter(send_raises=True, raise_text="secret-payload"), "backend_ctl")

    _run_bounded(lambda: adapter.on_inbound(_msg("corr-7")))

    assert adapter.get_stats()["lost_responses"] == 1
    assert len(captured.errors) == 1, captured.errors
    line = captured.errors[0]
    assert "RuntimeError" in line
    assert "corr-7" in line
    assert "secret-payload" not in line


def test_bridge_lost_counter_threaded() -> None:
    """Hazard: 4 потока x 50 ``on_inbound`` с ответом ``error`` — ровно 200 потерь."""
    adapter = SocketBridgeAdapter(_ScriptedRouter(send_result=dict(_SESSION_GONE)), "backend_ctl")
    start = threading.Barrier(4)
    errors: List[BaseException] = []

    def worker(n: int) -> None:
        try:
            start.wait(_JOIN_DEADLINE_S)
            for i in range(50):
                adapter.on_inbound(_msg(f"w{n}-{i}"))
        except BaseException as exc:  # noqa: BLE001 - пробросить в поток теста
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,), name=f"bridge-w{n}", daemon=True) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(_JOIN_DEADLINE_S)
    assert not any(thread.is_alive() for thread in threads), "потоки on_inbound не завершились за 5 с"
    assert errors == []
    assert adapter.get_stats()["lost_responses"] == 200
