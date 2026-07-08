# -*- coding: utf-8 -*-
"""Ф3.1 (routing-epoch): handler routing.refresh + команда routing.probe у ребёнка.

Fake-services поверх реального ProcessStateRegistry:
- refresh со сменившейся incarnation соседа → его очереди сброшены;
- epoch <= last_seen → ignored (очереди не тронуты);
- имя вне снимка → его очереди сброшены;
- своя запись и hub НЕ тронуты, даже если их incarnation расходится/отсутствует;
- probe зовёт send_to_process(target, inner).
"""

from __future__ import annotations

from multiprocessing import Queue

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.shared_resources_module.state.process_state_registry import (
    ProcessStateRegistry,
)


class _FakeCM:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, cmd, data=None) -> dict:
        return self.handlers[cmd](data or {})


class _FakeSR:
    def __init__(self, psr) -> None:
        self.process_state_registry = psr


class _FakeServices:
    def __init__(self, psr, name="devices") -> None:
        self.command_manager = _FakeCM()
        self.name = name
        self.shared_resources = _FakeSR(psr)
        self.error_manager = None
        self.sent: list = []

    def send_to_process(self, target, message) -> bool:
        self.sent.append((target, message))
        return True

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...
    def _log_error(self, *a, **k) -> None: ...


def _make_psr(entries: dict, *, self_epoch: int = 0) -> ProcessStateRegistry:
    """entries: {name: {"incarnation": int, "queues": [qtypes], "self": bool}}."""
    psr = ProcessStateRegistry()
    for name, spec in entries.items():
        epoch = self_epoch if spec.get("self") else 0
        psr.register_process(
            name,
            initial_state={
                "metadata": {
                    "routing_incarnation": spec.get("incarnation", 0),
                    "routing_epoch": epoch,
                }
            },
        )
        for qt in spec.get("queues", []):
            psr.add_queue(name, qt, Queue())
    return psr


def _make(psr, name="devices"):
    svc = _FakeServices(psr, name=name)
    BuiltinCommands(svc)._register_routing_commands()
    return svc, svc.command_manager


def _refresh(processes: dict, *, epoch: int, hub="ProcessManager") -> dict:
    return {"epoch": epoch, "hub": hub, "reason": "test", "processes": processes}


def _qcount(psr, name) -> int:
    return len(psr.get_process_data(name).queues)


# ---------------------------------------------------------------------------
# Регистрация
# ---------------------------------------------------------------------------


def test_both_commands_registered_with_own_reply():
    psr = _make_psr({"devices": {"self": True}})
    _svc, cm = _make(psr)
    assert "routing.probe" in cm.handlers
    assert "routing.refresh" in cm.handlers
    assert cm.metadata["routing.refresh"].get("manages_own_reply") is True


# ---------------------------------------------------------------------------
# refresh: сброс по incarnation
# ---------------------------------------------------------------------------


def test_reset_peer_on_incarnation_change():
    psr = _make_psr({
        "devices": {"self": True},
        "preprocessor": {"incarnation": 0, "queues": ["system", "data"]},
    })
    _svc, cm = _make(psr)
    res = cm.dispatch("routing.refresh", _refresh({"preprocessor": {"incarnation": 1}}, epoch=1))
    assert res["success"] is True
    assert "preprocessor" in res["reset"]
    assert _qcount(psr, "preprocessor") == 0
    # incarnation запомнена.
    assert psr.get_process_data("preprocessor").metadata["routing_incarnation"] == 1


def test_no_reset_when_incarnation_matches():
    psr = _make_psr({
        "devices": {"self": True},
        "preprocessor": {"incarnation": 2, "queues": ["system"]},
    })
    _svc, cm = _make(psr)
    res = cm.dispatch("routing.refresh", _refresh({"preprocessor": {"incarnation": 2}}, epoch=1))
    assert res["reset"] == []
    assert _qcount(psr, "preprocessor") == 1


# ---------------------------------------------------------------------------
# refresh: guard по epoch
# ---------------------------------------------------------------------------


def test_ignored_when_epoch_not_greater():
    psr = _make_psr(
        {
            "devices": {"self": True},
            "preprocessor": {"incarnation": 0, "queues": ["system"]},
        },
        self_epoch=5,
    )
    _svc, cm = _make(psr)
    res = cm.dispatch("routing.refresh", _refresh({"preprocessor": {"incarnation": 9}}, epoch=3))
    assert res.get("ignored") is True
    # Очередь НЕ тронута (устаревшая рассылка).
    assert _qcount(psr, "preprocessor") == 1


def test_applied_updates_last_seen_and_counter():
    psr = _make_psr({"devices": {"self": True}, "peer": {"incarnation": 0, "queues": ["system"]}})
    _svc, cm = _make(psr)
    cm.dispatch("routing.refresh", _refresh({"peer": {"incarnation": 1}}, epoch=1))
    meta = psr.get_process_data("devices").metadata
    assert meta["routing_epoch"] == 1
    assert meta["routing_refresh_applied"] == 1
    # Повтор того же epoch — ignored, счётчик не растёт.
    cm.dispatch("routing.refresh", _refresh({"peer": {"incarnation": 1}}, epoch=1))
    assert psr.get_process_data("devices").metadata["routing_refresh_applied"] == 1


# ---------------------------------------------------------------------------
# refresh: имя вне снимка + неприкосновенность self/hub
# ---------------------------------------------------------------------------


def test_reset_name_absent_from_snapshot():
    psr = _make_psr({
        "devices": {"self": True},
        "gone": {"incarnation": 0, "queues": ["system", "data"]},
        "alive": {"incarnation": 0, "queues": ["system"]},
    })
    _svc, cm = _make(psr)
    # gone отсутствует в снимке → сброшен; alive присутствует и совпадает → нет.
    res = cm.dispatch("routing.refresh", _refresh({"alive": {"incarnation": 0}}, epoch=1))
    assert "gone" in res["reset"]
    assert _qcount(psr, "gone") == 0
    assert _qcount(psr, "alive") == 1


def test_self_and_hub_never_touched():
    psr = _make_psr({
        "devices": {"self": True, "queues": ["system"]},
        "ProcessManager": {"incarnation": 0, "queues": ["system"]},
    })
    _svc, cm = _make(psr)
    # Снимок пуст (ни self, ни hub нет) + hub с иной incarnation — оба должны уцелеть.
    res = cm.dispatch("routing.refresh", _refresh({}, epoch=1, hub="ProcessManager"))
    assert res["reset"] == []
    assert _qcount(psr, "devices") == 1
    assert _qcount(psr, "ProcessManager") == 1


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


def test_probe_calls_send_to_process():
    psr = _make_psr({"devices": {"self": True}})
    svc, cm = _make(psr)
    inner = {"type": "command", "command": "health.report", "data": {}}
    res = cm.dispatch("routing.probe", {"target": "preprocessor", "inner": inner})
    assert res["success"] is True
    assert svc.sent == [("preprocessor", inner)]


def test_probe_rejects_bad_args():
    psr = _make_psr({"devices": {"self": True}})
    _svc, cm = _make(psr)
    assert cm.dispatch("routing.probe", {})["success"] is False
    assert cm.dispatch("routing.probe", {"target": "x"})["success"] is False
    assert cm.dispatch("routing.probe", {"target": "x", "inner": "not-a-dict"})["success"] is False
