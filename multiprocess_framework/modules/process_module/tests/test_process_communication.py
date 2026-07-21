# -*- coding: utf-8 -*-
"""Тесты для ProcessCommunication — send/receive через мок router."""

from unittest.mock import Mock

from ..communication.process_communication import ProcessCommunication
from ...router_module import RouterManager


def make_mock_router():
    """Мок RouterManager."""
    router = Mock()
    router.send = Mock(return_value={"status": "success"})
    router.receive = Mock(return_value=[])
    router.queue_registry = None
    router.get_channel = Mock(return_value=None)
    router.register_channel = Mock()
    return router


def make_mock_shared_resources(process_names=None):
    """Мок SharedResources."""
    sr = Mock()
    sr.process_state_registry = Mock()
    sr.process_state_registry.get_process_names = Mock(return_value=process_names or [])
    sr.get_process_data = Mock(return_value=None)
    sr.event_manager = None
    return sr


class TestProcessCommunicationSend:
    def test_send_dict_message(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)

        result = comm.send({"type": "test", "data": "hello"})

        router.send.assert_called_once()
        assert result["status"] == "success"

    def test_send_with_to_dict(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)

        msg = Mock()
        msg.to_dict = Mock(return_value={"type": "test"})

        comm.send(msg)
        router.send.assert_called_once_with({"type": "test"})

    def test_send_without_router_returns_error(self):
        comm = ProcessCommunication("proc1", {}, None)
        result = comm.send({"type": "test"})
        assert result["status"] == "error"

    def test_send_invalid_type_returns_error(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)
        result = comm.send("not a dict or message")
        assert result["status"] == "error"


class _FakeQueueRegistry:
    """Захватывает send_to_queue для проверки паритета доставки."""

    def __init__(self):
        self.sent = []

    def send_to_queue(self, target, qtype, msg):
        self.sent.append((target, qtype, msg))
        return True


class TestSendToProcessRoutesThroughRouter:
    """P1.3: send_to_process идёт через router.send → _deliver_by_targets → queue_registry.
    Паритет: та же очередь {target}_{qtype}, что и прежний прямой send_to_queue."""

    def test_command_lands_in_system_queue(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="proc1", queue_registry=qr)
        comm = ProcessCommunication("proc1", {}, router, shared_resources=None)

        ok = comm.send_to_process("worker_a", {"type": "command", "command": "do.thing"})

        assert ok is True
        assert len(qr.sent) == 1
        target, qtype, msg = qr.sent[0]
        assert target == "worker_a"
        assert qtype == "system"
        assert msg["sender"] == "proc1"
        assert msg["targets"] == ["worker_a"]

    def test_frame_lands_in_data_queue_and_channel_stripped(self):
        # recon #3: кадр несёт vestigial channel="data"; должен лечь в data-очередь,
        # vestigial channel снят (без WARNING-флуда), кадр НЕ потерян.
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="cam", queue_registry=qr)
        comm = ProcessCommunication("cam", {}, router, shared_resources=None)

        frame = {
            "type": "data",
            "channel": "data",
            "data": {"shm_name": "slot0", "shm_actual_name": "psm_1234"},
        }
        ok = comm.send_to_process("display_proc", frame)

        assert ok is True
        assert len(qr.sent) == 1
        target, qtype, msg = qr.sent[0]
        assert target == "display_proc"
        assert qtype == "data"
        assert "channel" not in msg  # vestigial снят
        assert msg["data"]["shm_actual_name"] == "psm_1234"  # Claim Check сохранён (recon #4)

    def test_send_message_alias_parity(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="p", queue_registry=qr)
        comm = ProcessCommunication("p", {}, router, shared_resources=None)

        comm.send_message("p2", {"type": "command", "command": "x"})
        assert qr.sent[0][0] == "p2"
        assert qr.sent[0][1] == "system"


class TestSystemEventsChannelNotRegistered:
    """LIVE-1: канал system_events БОЛЬШЕ не регистрируется (осиротевший — потребителя
    нет → EventManager.emit_event набивал очередь → рост errors PM ~13-57/с). emit_event
    гейтит отправку на наличие канала, поэтому его отсутствие само отключает рассылку."""

    def test_register_router_channels_skips_system_events(self):
        from queue import Queue as _TQ

        registered: list = []
        router = Mock()
        router.get_channel = Mock(return_value=None)
        router.register_channel = Mock(side_effect=lambda ch: registered.append(ch.name))
        comm = ProcessCommunication("proc1", {"system": _TQ(), "data": _TQ()}, router, shared_resources=None)
        comm.register_router_channels()
        # Свои per-qtype и local каналы регистрируются, а system_events — нет.
        assert "proc1_system" in registered
        assert "proc1_data" in registered
        assert "system_events" not in registered


class TestProcessCommunicationReceive:
    def test_receive_empty(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)
        messages = comm.receive(timeout=0.01)
        assert messages == []

    def test_receive_messages(self):
        router = make_mock_router()
        router.receive = Mock(return_value=[{"type": "ping"}, {"type": "pong"}])
        comm = ProcessCommunication("proc1", {}, router)

        messages = comm.receive(timeout=0.01)
        assert len(messages) == 2

    def test_receive_without_router_returns_empty(self):
        comm = ProcessCommunication("proc1", {}, None)
        assert comm.receive() == []


class TestProcessCommunicationAliases:
    def test_send_message_alias(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)

        result = comm.send_message("proc2", {"data": "test"})
        assert isinstance(result, bool)

    def test_broadcast_message_alias(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)

        result = comm.broadcast_message({"data": "broadcast"})
        assert isinstance(result, bool)

    def test_receive_message_alias_returns_single(self):
        router = make_mock_router()
        router.receive = Mock(return_value=[{"type": "ping"}])
        comm = ProcessCommunication("proc1", {}, router)

        msg = comm.receive_message(timeout=0.01)
        assert msg == {"type": "ping"}

    def test_receive_message_alias_returns_none_when_empty(self):
        router = make_mock_router()
        comm = ProcessCommunication("proc1", {}, router)

        msg = comm.receive_message()
        assert msg is None


class TestProcessCommunicationQueueStats:
    def test_queue_stats_empty(self):
        comm = ProcessCommunication("proc1", {}, None)
        stats = comm.get_queue_stats()
        assert stats == {}

    def test_queue_stats_with_queues(self):
        from multiprocessing import Queue

        q = Queue(maxsize=10)
        comm = ProcessCommunication("proc1", {"system": q}, None)

        stats = comm.get_queue_stats()
        assert "system" in stats
        assert "size" in stats["system"]
