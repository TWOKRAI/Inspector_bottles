# -*- coding: utf-8 -*-
"""C-36, живые тесты стенда (настоящий PM, headless-прототип). Написаны вслепую ДО реализации.

1. data-линия, 30 kill: после каждого ``kill`` + ``process.restart`` новое воплощение ``preprocessor``
   читает команды и data. Порог — 0 глухих из 30.
2. Билеты выжившего ``devices`` после рестарта доходят 30 из 30 и все идут через hub-relay PM.
3. Умолчание (без ``restart_reuse_queues`` в конфиге) поднимает incarnation при замене инстанса.

Счётчик data у потребителя — ``introspect.router_stats`` → ``received``. Он общий для system и data,
поэтому проверка data шлёт пачку из 50 билетов и требует прироста не меньше 25: служебный трафик за
окно измерения на порядок меньше. Тест 1 сам проверяет счётчик на живом воплощении ДО первого kill.
"""

from __future__ import annotations

import os
import signal
import time
from typing import Any

import pytest

from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap
from backend_ctl.tests.conftest import bookmark_cursor, page_events

_SENDER = "devices"  # protected: переживает рестарт соседа
_PEER = "preprocessor"
_PORT_KILLS = 8836
_PORT_RELAY = 8837
_PORT_INCARNATION = 8838

_KILLS = 30
_DATA_BURST = 50
_DATA_MIN_DELTA = 25
_RELAY_TICKETS = 30
_AFTER_READY_S = 5.0


def _dig(node: Any, key: str) -> dict:
    """Развернуть envelope ответа driver'а до dict с ``key`` (``{}`` — нет такого)."""
    for _ in range(4):
        if isinstance(node, dict) and key in node:
            return node
        node = node.get("result") if isinstance(node, dict) else None
    return {}


def _supervision(drv) -> dict:
    res = _dig(drv.supervision_status(_PEER, timeout=10.0), "processes")
    return (res.get("processes") or {}).get(_PEER) or {}


def _router_stat(drv, proc: str, name: str) -> int | None:
    stats = _dig(drv.introspect_router_stats(proc, timeout=1.0), "router_stats").get("router_stats")
    return None if stats is None else int(stats.get(name, 0) or 0)


def _restart_peer(drv) -> None:
    res = unwrap(
        drv.send_command("ProcessManager", "process.restart", {"process_name": _PEER}, timeout=60.0), leaf=True
    )
    assert res.get("success") is True, f"process.restart не success: {res}"


def _wait_new_instance(drv, old_pid: int) -> None:
    """Дождаться нового pid. Статус ждём до 30 с и дальше не судим: глухоту меряет окно после ready."""
    deadline = time.monotonic() + 30.0
    row: dict = {}
    while time.monotonic() < deadline:
        row = _supervision(drv)
        new = row.get("pid") not in (None, old_pid) and row.get("alive") is True
        if new and row.get("status") in ("running", "ready"):
            return
        time.sleep(0.2)
    assert row.get("pid") not in (None, old_pid) and row.get("alive") is True, f"новый инстанс не поднялся: {row}"


def _commands_ok(drv) -> int:
    """Сколько из 3 ``introspect.status`` получили ответ за 1 с."""
    ok = 0
    for _ in range(3):
        res = drv.introspect_status(_PEER, timeout=1.0)
        ok += isinstance(res, dict) and res.get("success") is True
    return ok


def _data_delta(drv, deadline_s: float) -> int:
    """Прирост ``received`` у потребителя после пачки data-билетов выжившего (0 — счётчик не читается)."""
    deadline = time.monotonic() + deadline_s
    before = _router_stat(drv, _PEER, "received")
    for i in range(_DATA_BURST):
        inner = {"type": "data", "command": "c36.data", "queue_type": "data", "data": {"i": i}}
        drv.send_command(_SENDER, "routing.probe", {"target": _PEER, "inner": inner}, timeout=5.0)
    if before is None:
        return 0
    delta = 0
    while True:
        time.sleep(0.5)
        after = _router_stat(drv, _PEER, "received")
        delta = delta if after is None else after - before
        if delta >= _DATA_MIN_DELTA or time.monotonic() >= deadline:
            return delta


@pytest.mark.harness_smoke
def test_data_line_30_kills_no_deaf_incarnation_live(monkeypatch, tmp_path) -> None:
    """30 раз kill по pid из ``supervision.status`` + ``process.restart``: глухих воплощений 0."""
    monkeypatch.setenv("FW_AUTORESTART", "0")  # иначе авто-рестарт гонится с process.restart
    harness = BackendHarness(with_base=True, run_gate=True, port=_PORT_KILLS, log_dir=tmp_path)
    drv = harness.start()
    try:
        # Контроль обвязки ДО первого kill: на заведомо живом воплощении обе пробы обязаны проходить.
        assert _commands_ok(drv) == 3, "обвязка непригодна: живой preprocessor не отвечает на команды"
        control = _data_delta(drv, _AFTER_READY_S)
        assert control >= _DATA_MIN_DELTA, f"счётчик data непригоден: прирост received={control} у живого"

        deaf: list[tuple[int, int, int]] = []
        for n in range(_KILLS):
            pid = _supervision(drv).get("pid")
            assert isinstance(pid, int) and pid > 0, f"kill #{n}: нет pid в supervision.status"
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))  # Windows: TerminateProcess
            gone_by = time.monotonic() + 10.0
            while _supervision(drv).get("alive") is True:
                assert time.monotonic() < gone_by, f"kill #{n}: pid {pid} не умер за 10 с"
                time.sleep(0.1)
            _restart_peer(drv)
            _wait_new_instance(drv, pid)

            ready_at = time.monotonic()
            commands = _commands_ok(drv)
            data = _data_delta(drv, max(0.0, _AFTER_READY_S - (time.monotonic() - ready_at)))
            if commands == 0 or data < _DATA_MIN_DELTA:
                deaf.append((n, commands, data))
            print(f"[c36] kill #{n}: commands={commands}/3 data_delta={data}")

        assert len(deaf) == 0, f"глухих {len(deaf)}/30 (номер, команд из 3, прирост data): {deaf}"
        assert _supervision(drv).get("instance_restarts") == 30, "счётчик замен не 30: гонка с авто-рестартом"
    finally:
        harness.stop()


def _health_report(drv, tag: str) -> None:
    inner = {"type": "command", "command": "health.report", "data": {"context": "c36-relay", "message": tag}}
    drv.send_command(_SENDER, "routing.probe", {"target": _PEER, "inner": inner}, timeout=5.0)


def _wait_health_errors(drv, cursor, minimum: int, timeout_s: float) -> tuple[int | None, Any]:
    path = f"processes.{_PEER}.health.errors"
    deadline = time.monotonic() + timeout_s
    latest: int | None = None
    while time.monotonic() < deadline:
        events, cursor = page_events(drv, cursor)
        for event in events:
            if event.get("command") != "state.changed":
                continue
            for delta in (event.get("data") or {}).get("deltas", []) or []:
                if delta.get("path") == path:
                    latest = delta.get("new_value")
        if isinstance(latest, int) and latest >= minimum:
            break
        if not events:
            time.sleep(0.2)
    return latest, cursor


@pytest.mark.harness_smoke
def test_survivor_tickets_reach_restarted_consumer_all_via_relay_live(tmp_path) -> None:
    """После рестарта ``preprocessor``: 30 из 30 билетов ``devices`` дошли, все 30 — через relay PM."""
    harness = BackendHarness(with_base=True, port=_PORT_RELAY, log_dir=tmp_path)
    drv = harness.start()
    try:
        sub = unwrap(drv.state_subscribe(f"processes.{_PEER}.**", timeout=8.0), leaf=True)
        assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"
        cursor = bookmark_cursor(drv)
        _health_report(drv, "baseline")
        baseline, cursor = _wait_health_errors(drv, cursor, 1, 20.0)
        assert baseline is not None and baseline >= 1, f"baseline-билет не доставлен: {baseline}"

        old_pid = _supervision(drv).get("pid")
        _restart_peer(drv)
        _wait_new_instance(drv, old_pid)
        time.sleep(3.0)  # refresh у выжившего + первый heartbeat нового
        cursor = bookmark_cursor(drv)
        relayed_before = _router_stat(drv, _SENDER, "relayed_to_hub")

        for i in range(_RELAY_TICKETS):
            _health_report(drv, f"post-restart:{i}")
        errors, cursor = _wait_health_errors(drv, cursor, 30, 20.0)
        relayed_after = _router_stat(drv, _SENDER, "relayed_to_hub")

        assert errors == 30, f"дошло билетов: {errors}, ожидалось 30"
        assert relayed_before is not None and relayed_after is not None, "router_stats выжившего не читается"
        assert relayed_after - relayed_before == 30, f"через relay: {relayed_before} -> {relayed_after}"
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_default_restart_bumps_incarnation_live(tmp_path) -> None:
    """Без ``restart_reuse_queues`` в конфиге замена инстанса даёт новые очереди — incarnation растёт."""
    harness = BackendHarness(with_base=True, port=_PORT_INCARNATION, log_dir=tmp_path)
    drv = harness.start()
    try:
        before = _supervision(drv).get("incarnation")
        assert isinstance(before, int), f"нет incarnation до рестарта: {before}"
        _restart_peer(drv)
        after = _supervision(drv).get("incarnation")
        assert after == before + 1, f"incarnation: {before} -> {after}"
    finally:
        harness.stop()
