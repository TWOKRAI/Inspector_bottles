"""
Тесты для types/types.py.
"""

import pickle
import pytest
from ..types import ProcessStatus, ResourceType, EventType, ProcessDataDict, QueueConfigDict, MemoryConfigDict


class TestProcessStatus:
    def test_all_values_exist(self):
        expected = {"initializing", "ready", "running", "stopping", "stopped", "error"}
        assert {s.value for s in ProcessStatus} == expected

    def test_from_string(self):
        assert ProcessStatus("running") == ProcessStatus.RUNNING

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            ProcessStatus("unknown_status")

    def test_pickle_roundtrip(self):
        for status in ProcessStatus:
            assert pickle.loads(pickle.dumps(status)) == status


class TestResourceType:
    def test_all_values_exist(self):
        expected = {"queue", "event", "shared_memory"}
        assert {r.value for r in ResourceType} == expected

    def test_pickle_roundtrip(self):
        for rt in ResourceType:
            assert pickle.loads(pickle.dumps(rt)) == rt


class TestEventType:
    def test_all_values_exist(self):
        expected = {
            "process_registered", "process_state_changed", "process_unregistered",
            "queue_added", "event_added", "config_updated",
        }
        assert {e.value for e in EventType} == expected

    def test_from_string(self):
        assert EventType("queue_added") == EventType.QUEUE_ADDED

    def test_pickle_roundtrip(self):
        for et in EventType:
            assert pickle.loads(pickle.dumps(et)) == et


class TestTypedDicts:
    def test_process_data_dict_keys(self):
        d: ProcessDataDict = {
            "name": "p1",
            "status": "running",
            "metadata": {},
            "custom": {},
            "queue_types": ["system"],
            "event_names": ["stop"],
        }
        assert d["name"] == "p1"
        assert d["status"] == "running"

    def test_queue_config_dict(self):
        cfg: QueueConfigDict = {"maxsize": 100}
        assert cfg["maxsize"] == 100

    def test_memory_config_dict(self):
        cfg: MemoryConfigDict = {
            "num_images": 4,
            "image_shape": (480, 640, 3),
            "dtype": "uint8",
            "coll": 2,
        }
        assert cfg["coll"] == 2
