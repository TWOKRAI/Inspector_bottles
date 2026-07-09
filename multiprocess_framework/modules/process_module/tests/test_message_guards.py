# -*- coding: utf-8 -*-
"""Ф4.2: проводка message-guards (fencing-token + реестр контрактов) у ребёнка.

Fake-services поверх реального ProcessStateRegistry и реального RouterManager:
- fence-штамп на send control-plane (epoch/incarnation из своей PSR-записи);
- fence-фильтр на receive дропает стейл epoch + растит fence_dropped;
- FW_FENCE=0 → штамп/фильтр не вешаются (откат);
- контракт warn: нарушение логируется + contract_violations, но проходит;
- контракт strict: нарушение дропается.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from multiprocess_framework.modules.message_module import FENCE_KEY, read_fence
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.shared_resources_module.state.process_state_registry import (
    ProcessStateRegistry,
)


class _Ping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    command: str
    count: int = 0


class _FakeSR:
    def __init__(self, psr) -> None:
        self.process_state_registry = psr


class _FakeServices:
    def __init__(self, psr, router, name="devices") -> None:
        self.name = name
        self.shared_resources = _FakeSR(psr)
        self.router_manager = router
        self.command_manager = None
        self.warnings: list = []

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...
    def _log_error(self, *a, **k) -> None: ...

    def _log_warning(self, msg, *a, **k) -> None:
        self.warnings.append(msg)


def _psr(*, own_inc: int = 2, peer_inc: int = 3, name="devices") -> ProcessStateRegistry:
    """PSR со своей записью (own_inc) и записью соседа 'peer' (peer_inc)."""
    psr = ProcessStateRegistry()
    psr.register_process(
        name,
        initial_state={"metadata": {"routing_epoch": 5, "routing_incarnation": own_inc}},
    )
    psr.register_process(
        "peer",
        initial_state={"metadata": {"routing_epoch": 5, "routing_incarnation": peer_inc}},
    )
    return psr


def _wire(monkeypatch, *, fence="1", strict=None, own_inc=2, peer_inc=3):
    if fence is None:
        monkeypatch.delenv("FW_FENCE", raising=False)
    else:
        monkeypatch.setenv("FW_FENCE", fence)
    if strict is None:
        monkeypatch.delenv("FW_CONTRACTS_STRICT", raising=False)
    else:
        monkeypatch.setenv("FW_CONTRACTS_STRICT", strict)
    psr = _psr(own_inc=own_inc, peer_inc=peer_inc)
    router = RouterManager("devices")
    svc = _FakeServices(psr, router)
    BuiltinCommands(svc)._register_message_guards()
    return svc, router


# --------------------------------------------------------------------------- #
# Fencing
# --------------------------------------------------------------------------- #

def test_registry_attached_with_builtin_contracts(monkeypatch):
    """Ф4.2 шаг 6: реестр наполнен контрактами built-in команд (wire.configure и т.п.)."""
    svc, _ = _wire(monkeypatch)
    assert svc.contract_registry is not None
    assert "wire.configure" in svc.contract_registry
    assert "routing.probe" in svc.contract_registry


def test_send_stamps_control_plane_from_psr(monkeypatch):
    _, router = _wire(monkeypatch, own_inc=2)
    out = router._send_mw.apply({"type": "command", "command": "start", "sender": "devices"})
    assert read_fence(out) == {"sender": "devices", "inc": 2, "epoch": 5}


def test_send_skips_data_frame(monkeypatch):
    _, router = _wire(monkeypatch)
    out = router._send_mw.apply({"type": "data", "data_type": "frame"})
    assert FENCE_KEY not in out


def test_receive_drops_stale_instance_and_counts(monkeypatch):
    # peer текущий inc=3 в PSR; билет от старого инстанса peer (inc=2) → дроп.
    _, router = _wire(monkeypatch, peer_inc=3)
    out = router._recv_mw.apply({"type": "command", "command": "x", "_fence": {"sender": "peer", "inc": 2}})
    assert out is None
    assert router._stats["fence_dropped"] == 1


def test_receive_passes_current_instance(monkeypatch):
    _, router = _wire(monkeypatch, peer_inc=3)
    msg = {"type": "command", "command": "x", "_fence": {"sender": "peer", "inc": 3}}
    assert router._recv_mw.apply(msg) is msg
    assert router._stats["fence_dropped"] == 0


def test_receive_fail_open_unknown_sender(monkeypatch):
    _, router = _wire(monkeypatch)
    msg = {"type": "command", "command": "x", "_fence": {"sender": "stranger", "inc": 0}}
    assert router._recv_mw.apply(msg) is msg  # нет записи 'stranger' в PSR → проходит
    assert router._stats["fence_dropped"] == 0


def test_fence_off_disables_stamp(monkeypatch):
    _, router = _wire(monkeypatch, fence="0")
    out = router._send_mw.apply({"type": "command", "command": "start"})
    assert FENCE_KEY not in out
    # и фильтр не повешен — стейл проходит
    stale = {"type": "command", "_fence": {"sender": "peer", "inc": 0}}
    assert router._recv_mw.apply(stale) is stale


# --------------------------------------------------------------------------- #
# Контракты (warn / strict)
# --------------------------------------------------------------------------- #

def test_contract_warn_logs_but_passes(monkeypatch):
    svc, router = _wire(monkeypatch, fence="0")  # fence off — изолируем контракт
    # Реестр — тот же объект, что уже держит установленный middleware: наполнение
    # видно без повторной проводки.
    svc.contract_registry.register("ping", _Ping)
    bad = {"type": "command", "command": "ping"}  # нет обязательного id
    out = router._recv_mw.apply(bad)
    assert out is bad  # warn не дропает
    assert router._stats["contract_violations"] == 1
    assert any("ping" in w for w in svc.warnings)


def test_contract_strict_drops(monkeypatch):
    svc, router = _wire(monkeypatch, fence="0", strict="1")
    svc.contract_registry.register("ping", _Ping)
    bad = {"type": "command", "command": "ping"}
    assert router._recv_mw.apply(bad) is None  # strict дропает
    assert router._stats["contract_violations"] == 1


def test_no_router_is_noop():
    class _Svc:
        router_manager = None

    # не должно падать
    BuiltinCommands(_Svc())._register_message_guards()
