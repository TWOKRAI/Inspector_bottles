# -*- coding: utf-8 -*-
"""Тесты для ProcessCommunication — send/receive через мок router."""

import pytest
from unittest.mock import Mock, MagicMock

from ..communication.process_communication import ProcessCommunication


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
