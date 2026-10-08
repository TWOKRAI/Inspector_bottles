"""Контрактные тесты IProcessCommunication (k0 1.1).

Purpose: закрепить Protocol из 11 членов и явное наследование ProcessCommunication от него.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite
"""

from unittest.mock import Mock

from multiprocess_framework.modules.process_module.communication.process_communication import (
    ProcessCommunication,
)
from multiprocess_framework.modules.process_module.interfaces import IProcessCommunication

__all__: list[str] = []

# Литерал из ``atlas ref process_module`` (brief tasks/1.1.md).
_MEMBERS = (
    "send", "receive", "send_to_process", "broadcast", "send_message", "broadcast_message",
    "receive_message", "register_process_queues", "register_router_channels",
    "unregister_process", "get_queue_stats",
)  # fmt: skip


def _stub(names):
    return type("Stub", (), {n: (lambda self, *a, **k: None) for n in names})()


def test_iprocess_communication_protocol_needs_every_one_of_11_members():
    assert len(_MEMBERS) == 11
    assert isinstance(_stub(_MEMBERS), IProcessCommunication)
    for missing in _MEMBERS:
        partial = _stub([n for n in _MEMBERS if n != missing])
        assert not isinstance(partial, IProcessCommunication), missing


def test_process_communication_is_an_explicit_iprocess_communication():
    assert IProcessCommunication in ProcessCommunication.__mro__
    comm = ProcessCommunication("proc1", {}, Mock())
    assert isinstance(comm, IProcessCommunication)
