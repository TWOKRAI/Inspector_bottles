# -*- coding: utf-8 -*-
"""Тесты для ProcessIO — facade-хелпер для IPC/SHM/logs."""

from unittest.mock import Mock

import pytest

from ..io.process_io import ProcessIO


def make_mock_process(name: str = "test_proc", with_memory: bool = True):
    """Мок ProcessModule с необходимым минимумом атрибутов."""
    proc = Mock()
    proc.name = name
    proc.send_message = Mock(return_value=True)
    proc._log_info = Mock()
    proc._log_error = Mock()
    if with_memory:
        mm = Mock()
        mm.find_free_index = Mock(return_value=3)
        mm.write_images = Mock(return_value="actual_shm_name_007")
        proc.memory_manager = mm
    else:
        proc.memory_manager = None
    return proc


# ============================================================================
# IPC: send_data / send_command / send_event
# ============================================================================


class TestSendData:
    def test_send_data_builds_message_and_sends(self):
        proc = make_mock_process("camera")
        io = ProcessIO(proc)

        result = io.send_data("processor", "frame_ready", {"frame_id": 42})

        assert result is True
        proc.send_message.assert_called_once()
        target, msg_dict = proc.send_message.call_args.args
        assert target == "processor"
        assert msg_dict["type"] == "data"
        assert msg_dict["data_type"] == "frame_ready"
        assert msg_dict["data"] == {"frame_id": 42}
        assert msg_dict["sender"] == "camera"
        assert msg_dict["targets"] == ["processor"]

    def test_send_data_returns_transport_result(self):
        proc = make_mock_process()
        proc.send_message = Mock(return_value=False)
        io = ProcessIO(proc)

        assert io.send_data("gui", "status", {}) is False


class TestSendCommand:
    def test_send_command_builds_message(self):
        proc = make_mock_process("processor")
        io = ProcessIO(proc)

        io.send_command(
            "database",
            "db.save_detections",
            {"detections": [{"id": 1}]},
        )

        target, msg_dict = proc.send_message.call_args.args
        assert target == "database"
        assert msg_dict["type"] == "command"
        assert msg_dict["command"] == "db.save_detections"
        assert msg_dict["args"] == {"detections": [{"id": 1}]}

    def test_send_command_with_explicit_data(self):
        proc = make_mock_process()
        io = ProcessIO(proc)

        io.send_command("robot", "reject_item", {"frame_id": 5}, data={"x": 1})

        _, msg_dict = proc.send_message.call_args.args
        assert msg_dict["data"] == {"x": 1}


class TestSendEvent:
    def test_send_event_builds_message(self):
        proc = make_mock_process("processor")
        io = ProcessIO(proc)

        io.send_event("camera", "frame_processed", {"frame_id": 7, "time": 0.05})

        target, msg_dict = proc.send_message.call_args.args
        assert target == "camera"
        assert msg_dict["type"] == "event"
        assert msg_dict["event_type"] == "frame_processed"
        assert msg_dict["event_data"] == {"frame_id": 7, "time": 0.05}


# ============================================================================
# SHM: write_frames_to_shm
# ============================================================================


class TestWriteFramesToShm:
    def test_returns_shm_info_dict(self):
        proc = make_mock_process()
        io = ProcessIO(proc)

        result = io.write_frames_to_shm("camera", "camera_frame", ["<frame>"])

        assert result == {
            "shm_name": "camera_frame",
            "shm_index": 3,
            "shm_actual_name": "actual_shm_name_007",
        }
        proc.memory_manager.find_free_index.assert_called_once_with(
            "camera", "camera_frame"
        )
        proc.memory_manager.write_images.assert_called_once_with(
            "camera", "camera_frame", ["<frame>"], 3
        )

    def test_free_index_none_falls_back_to_zero(self):
        proc = make_mock_process()
        proc.memory_manager.find_free_index = Mock(return_value=None)
        io = ProcessIO(proc)

        result = io.write_frames_to_shm("x", "slot", ["f"])

        assert result["shm_index"] == 0
        proc.memory_manager.write_images.assert_called_once_with("x", "slot", ["f"], 0)

    def test_returns_none_when_no_memory_manager(self):
        proc = make_mock_process(with_memory=False)
        io = ProcessIO(proc)

        assert io.write_frames_to_shm("x", "slot", ["f"]) is None

    def test_returns_none_when_write_fails(self):
        proc = make_mock_process()
        proc.memory_manager.write_images = Mock(return_value=None)
        io = ProcessIO(proc)

        assert io.write_frames_to_shm("x", "slot", ["f"]) is None


# ============================================================================
# Logs
# ============================================================================


class TestLogs:
    def test_log_info_delegates(self):
        proc = make_mock_process()
        io = ProcessIO(proc)

        io.log_info("started")
        proc._log_info.assert_called_once_with("started")

    def test_log_error_delegates(self):
        proc = make_mock_process()
        io = ProcessIO(proc)

        io.log_error("boom")
        proc._log_error.assert_called_once_with("boom")


# ============================================================================
# Инициализация
# ============================================================================


class TestInit:
    def test_message_adapter_uses_process_name(self):
        proc = make_mock_process("my_proc")
        io = ProcessIO(proc)

        io.send_data("x", "t", {})
        _, msg_dict = proc.send_message.call_args.args
        assert msg_dict["sender"] == "my_proc"
