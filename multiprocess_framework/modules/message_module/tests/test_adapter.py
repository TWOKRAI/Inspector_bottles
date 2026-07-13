# -*- coding: utf-8 -*-
"""
Тесты для MessageAdapter.

Проверяет:
- Создание адаптера и фиксацию sender
- Каждый метод-шаблон (command, log, system, broadcast, data, request, response, event)
- Fluent API через адаптер
- Dict at Boundary (to_dict() после каждого шаблона)
- Валидацию после создания
- Edge-cases: пустой sender, одиночный target как строка
"""

import pytest

from ..adapters.message_adapter import MessageAdapter
from ..types.message_types import MessageType, LogLevel


SENDER = "test_process"


@pytest.fixture
def adapter():
    return MessageAdapter(sender=SENDER)


# =============================================================================
# Базовые тесты
# =============================================================================


class TestAdapterInit:
    def test_sender_stored(self, adapter):
        assert adapter.sender == SENDER

    def test_repr(self, adapter):
        assert SENDER in repr(adapter)

    def test_empty_sender_raises(self):
        with pytest.raises(ValueError, match="sender cannot be empty"):
            MessageAdapter(sender="")


# =============================================================================
# Метод create()
# =============================================================================


class TestCreate:
    def test_create_general(self, adapter):
        msg = adapter.create(MessageType.GENERAL, ["proc_2"], content="hello")
        assert msg.type == "general"
        assert msg.sender == SENDER
        assert msg.targets == ["proc_2"]
        assert msg.content == "hello"

    def test_create_string_target(self, adapter):
        msg = adapter.create("command", "proc_2", command="ping")
        assert msg.targets == ["proc_2"]

    def test_create_assigns_id(self, adapter):
        msg = adapter.create("general", ["proc_2"])
        assert msg.id
        assert len(msg.id) > 0

    def test_create_assigns_timestamp(self, adapter):
        import time

        before = time.time()
        msg = adapter.create("general", ["proc_2"])
        after = time.time()
        assert before <= msg.timestamp <= after


# =============================================================================
# command()
# =============================================================================


class TestCommand:
    def test_basic(self, adapter):
        msg = adapter.command(targets=["proc_2"], command="start")
        assert msg.type == "command"
        assert msg.sender == SENDER
        assert msg.targets == ["proc_2"]
        assert msg.command == "start"

    def test_with_args(self, adapter):
        # Единый конверт (Ф7 G.2): payload едет под data, не под args.
        msg = adapter.command("proc_2", "configure", args={"key": "val"})
        assert msg.data == {"key": "val"}
        assert msg.data_type == "configure"

    def test_default_priority_normal(self, adapter):
        msg = adapter.command("proc_2", "ping")
        assert msg.priority == "normal"

    def test_custom_priority(self, adapter):
        msg = adapter.command("proc_2", "stop", priority="urgent")
        assert msg.priority == "urgent"

    def test_need_ack(self, adapter):
        msg = adapter.command("proc_2", "shutdown", need_ack=True)
        assert msg.need_ack is True

    def test_to_dict_has_command(self, adapter):
        msg = adapter.command("proc_2", "ping")
        d = msg.to_dict()
        assert d["command"] == "ping"
        assert d["type"] == "command"
        assert d["sender"] == SENDER

    def test_string_targets(self, adapter):
        msg = adapter.command("proc_2", "ping")
        assert msg.targets == ["proc_2"]

    def test_list_targets(self, adapter):
        msg = adapter.command(["proc_2", "proc_3"], "ping")
        assert msg.targets == ["proc_2", "proc_3"]


# =============================================================================
# log()
# =============================================================================


class TestLog:
    def test_basic(self, adapter):
        msg = adapter.log("info", "Process started")
        assert msg.type == "log"
        assert msg.level == "info"
        assert msg.message == "Process started"

    def test_default_targets_logger(self, adapter):
        msg = adapter.log("debug", "test")
        assert "logger" in msg.targets

    def test_default_module_is_sender(self, adapter):
        msg = adapter.log("info", "test")
        assert msg.module == SENDER

    def test_custom_module(self, adapter):
        msg = adapter.log("warning", "test", module="sub_component")
        assert msg.module == "sub_component"

    def test_log_level_enum(self, adapter):
        msg = adapter.log(LogLevel.ERROR, "boom")
        assert msg.level == "error"

    def test_log_level_string(self, adapter):
        msg = adapter.log("critical", "critical error")
        assert msg.level == "critical"

    def test_to_dict(self, adapter):
        msg = adapter.log("info", "hello")
        d = msg.to_dict()
        assert d["type"] == "log"
        assert d["level"] == "info"
        assert d["message"] == "hello"


# =============================================================================
# system()
# =============================================================================


class TestSystem:
    def test_basic(self, adapter):
        msg = adapter.system(targets=["orchestrator"], action="shutdown")
        assert msg.type == "system"
        assert msg.action == "shutdown"
        assert "orchestrator" in msg.targets

    def test_default_priority_high(self, adapter):
        msg = adapter.system("orchestrator", "restart")
        assert msg.priority == "high"

    def test_with_data(self, adapter):
        msg = adapter.system("orchestrator", "configure", data={"timeout": 30})
        assert msg.data == {"timeout": 30}


# =============================================================================
# broadcast()
# =============================================================================


class TestBroadcast:
    def test_basic(self, adapter):
        msg = adapter.broadcast(content="hello world")
        assert msg.type == "broadcast"
        assert msg.targets == ["all"]
        assert msg.content == "hello world"

    def test_exclude(self, adapter):
        msg = adapter.broadcast("update", exclude=["proc_3"])
        assert msg.exclude == ["proc_3"]

    def test_default_exclude_empty(self, adapter):
        msg = adapter.broadcast("ping")
        assert msg.exclude == [] or "exclude" not in msg.to_dict()


# =============================================================================
# data()
# =============================================================================


class TestData:
    def test_basic(self, adapter):
        msg = adapter.data(targets=["proc_2"], data_type="frame", data=b"bytes")
        assert msg.type == "data"
        assert msg.data_type == "frame"
        assert msg.data == b"bytes"

    def test_shared_memory(self, adapter):
        msg = adapter.data("proc_2", "tensor", use_shared_memory=True, memory_key="shm_key_1")
        assert msg.use_shared_memory is True
        assert msg.memory_key == "shm_key_1"

    def test_to_dict(self, adapter):
        msg = adapter.data("proc_2", "result", data={"score": 0.99})
        d = msg.to_dict()
        assert d["data_type"] == "result"


# =============================================================================
# request()
# =============================================================================


class TestRequest:
    def test_basic(self, adapter):
        msg = adapter.request(targets=["service"], request_type="get_status")
        assert msg.type == "request"
        assert msg.request_type == "get_status"
        assert "service" in msg.targets

    def test_default_timeout(self, adapter):
        msg = adapter.request("service", "ping")
        assert msg.timeout == 5.0

    def test_custom_timeout(self, adapter):
        msg = adapter.request("service", "heavy_query", timeout=30.0)
        assert msg.timeout == 30.0

    def test_with_query(self, adapter):
        msg = adapter.request("db", "query", query={"key": "abc"})
        assert msg.query == {"key": "abc"}

    def test_id_usable_as_correlation_id(self, adapter):
        msg = adapter.request("service", "get_data")
        correlation_id = msg.id
        assert correlation_id.startswith("req_")


# =============================================================================
# response()
# =============================================================================


class TestResponse:
    def test_basic(self, adapter):
        msg = adapter.response(
            targets=["requester"],
            request_id="req_abc123",
            result={"value": 42},
        )
        assert msg.type == "response"
        assert msg.request_id == "req_abc123"
        assert msg.result == {"value": 42}
        assert msg.success is True

    def test_error_response(self, adapter):
        msg = adapter.response(
            targets=["requester"],
            request_id="req_abc123",
            success=False,
            error="Not found",
        )
        assert msg.success is False
        assert msg.error == "Not found"

    def test_to_dict(self, adapter):
        msg = adapter.response("requester", "req_xyz", result="ok")
        d = msg.to_dict()
        assert d["request_id"] == "req_xyz"
        assert d["success"] is True


# =============================================================================
# event()
# =============================================================================


class TestEvent:
    def test_basic(self, adapter):
        msg = adapter.event("frame_ready", event_data={"frame_id": 1})
        assert msg.type == "event"
        assert msg.event_type == "frame_ready"
        assert msg.event_data == {"frame_id": 1}

    def test_default_targets_all(self, adapter):
        msg = adapter.event("config_changed")
        assert "all" in msg.targets

    def test_custom_targets_string(self, adapter):
        msg = adapter.event("done", targets="proc_2")
        assert "proc_2" in msg.targets

    def test_custom_targets_list(self, adapter):
        msg = adapter.event("done", targets=["proc_2", "proc_3"])
        assert msg.targets == ["proc_2", "proc_3"]


# =============================================================================
# Dict at Boundary
# =============================================================================


class TestDictAtBoundary:
    """Все сообщения должны корректно сериализоваться и десериализоваться."""

    def test_roundtrip_command(self, adapter):
        from ..core.message import Message

        original = adapter.command("proc_2", "start", args={"timeout": 10})
        raw = original.to_dict()
        restored = Message.from_dict(raw)
        assert restored.type == original.type
        assert restored.command == original.command
        assert restored.sender == original.sender
        assert restored.targets == original.targets

    def test_roundtrip_log(self, adapter):
        from ..core.message import Message

        original = adapter.log("warning", "disk low")
        raw = original.to_dict()
        restored = Message.from_dict(raw)
        assert restored.level == "warning"
        assert restored.message == "disk low"

    def test_roundtrip_response(self, adapter):
        from ..core.message import Message

        original = adapter.response("requester", "req_1", result={"ok": True})
        raw = original.to_dict()
        restored = Message.from_dict(raw)
        assert restored.request_id == "req_1"
        assert restored.result == {"ok": True}

    def test_to_dict_excludes_private_fields(self, adapter):
        msg = adapter.command("proc_2", "ping")
        d = msg.to_dict()
        for key in d:
            assert not key.startswith("_"), f"Private field leaked: {key}"

    def test_to_json_roundtrip(self, adapter):
        from ..core.message import Message

        original = adapter.event("test_event", event_data=42)
        json_str = original.to_json()
        restored = Message.from_json(json_str)
        assert restored.event_type == "test_event"
        assert restored.event_data == 42


# =============================================================================
# Изоляция sender'ов
# =============================================================================


class TestMultipleAdapters:
    def test_different_senders(self):
        a1 = MessageAdapter("process_1")
        a2 = MessageAdapter("process_2")
        msg1 = a1.command("proc_3", "ping")
        msg2 = a2.command("proc_3", "ping")
        assert msg1.sender == "process_1"
        assert msg2.sender == "process_2"

    def test_adapters_independent(self):
        a1 = MessageAdapter("p1")
        a2 = MessageAdapter("p2")
        m1 = a1.log("info", "hello from p1")
        m2 = a2.log("info", "hello from p2")
        assert m1.module == "p1"
        assert m2.module == "p2"
