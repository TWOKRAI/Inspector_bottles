"""
Тесты validation.py — валидация доступа к SharedMemory.

Не требуют SharedMemory, работают на всех платформах.
"""

import pytest

from ..validation import (
    clear_memory_slot,
    validate_memory_access,
    validate_write_operation,
)


class TestValidateMemoryAccess:
    def test_none_memory_data_returns_false(self):
        assert validate_memory_access(None, "shm", 0) is False

    def test_empty_dict_returns_false(self):
        assert validate_memory_access({}, "shm", 0) is False

    def test_valid_access_returns_true(self):
        memory_data = {
            "handles": [object(), object()],
            "coll": {"shm": 2},
        }
        assert validate_memory_access(memory_data, "shm", 0) is True
        assert validate_memory_access(memory_data, "shm", 1) is True

    def test_invalid_index_returns_false(self):
        memory_data = {
            "handles": [object(), object()],
            "coll": {"shm": 2},
        }
        assert validate_memory_access(memory_data, "shm", 2) is False
        assert validate_memory_access(memory_data, "shm", -1) is False

    def test_missing_shm_in_coll_returns_false(self):
        memory_data = {
            "handles": [object()],
            "coll": {"other": 1},
        }
        assert validate_memory_access(memory_data, "shm", 0) is False

    def test_none_handle_returns_false(self):
        memory_data = {
            "handles": [object(), None],
            "coll": {"shm": 2},
        }
        assert validate_memory_access(memory_data, "shm", 0) is True
        assert validate_memory_access(memory_data, "shm", 1) is False


class TestValidateWriteOperation:
    def test_none_memory_data_returns_false(self):
        assert validate_write_operation(None, "shm", 0, 1) is False

    def test_invalid_access_returns_false(self):
        memory_data = {"handles": [], "coll": {"shm": 1}, "params": {"shm": (2, (10, 10, 3), None)}}
        assert validate_write_operation(memory_data, "shm", 0, 1) is False

    def test_too_many_images_returns_false(self):
        memory_data = {
            "handles": [object()],
            "coll": {"shm": 1},
            "params": {"shm": (2, (10, 10, 3), None)},
        }
        assert validate_write_operation(memory_data, "shm", 0, 3) is False

    def test_valid_write_returns_true(self):
        memory_data = {
            "handles": [object()],
            "coll": {"shm": 1},
            "params": {"shm": (2, (10, 10, 3), None)},
        }
        assert validate_write_operation(memory_data, "shm", 0, 1) is True
        assert validate_write_operation(memory_data, "shm", 0, 2) is True


class TestClearMemorySlot:
    def test_none_handles_noop(self):
        clear_memory_slot(None, 0)

    def test_empty_handles_noop(self):
        clear_memory_slot([], 0)

    def test_invalid_index_noop(self):
        class FakeShm:
            size = 100
            buf = bytearray(100)

        handles = [FakeShm()]
        clear_memory_slot(handles, 1)
