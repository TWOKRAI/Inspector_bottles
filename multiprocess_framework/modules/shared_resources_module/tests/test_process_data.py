"""
Тесты для state/process_data.py.
"""

import pickle
import time
from multiprocessing import Queue, Event


from ..state.process_data import ProcessData, QueuesProxy, EventsProxy
from ..types import ProcessStatus


class TestQueuesProxy:
    def test_attribute_access(self):
        q = Queue()
        proxy = QueuesProxy({"system": q})
        assert proxy.system is q

    def test_missing_attribute_returns_none(self):
        proxy = QueuesProxy({})
        assert proxy.nonexistent is None

    def test_contains(self):
        proxy = QueuesProxy({"data": Queue()})
        assert "data" in proxy
        assert "other" not in proxy

    def test_iter(self):
        proxy = QueuesProxy({"a": Queue(), "b": Queue()})
        assert set(proxy) == {"a", "b"}

    def test_len(self):
        proxy = QueuesProxy({"a": Queue(), "b": Queue()})
        assert len(proxy) == 2

    def test_pickle_roundtrip(self):
        """Queue pickle работает только при передаче через Process (spawn).
        В unit-тесте проверяем что __getstate__/__setstate__ корректны без Queue."""
        proxy = QueuesProxy({"system": None, "data": None})
        proxy2 = pickle.loads(pickle.dumps(proxy))
        assert "system" in proxy2
        assert "data" in proxy2


class TestEventsProxy:
    def test_attribute_access(self):
        e = Event()
        proxy = EventsProxy({"stop": e})
        assert proxy.stop is e

    def test_missing_attribute_returns_none(self):
        proxy = EventsProxy({})
        assert proxy.nonexistent is None

    def test_pickle_roundtrip(self):
        """Event pickle работает только при передаче через Process (spawn).
        В unit-тесте проверяем структуру без Event объектов."""
        proxy = EventsProxy({"stop": None, "pause": None})
        proxy2 = pickle.loads(pickle.dumps(proxy))
        assert "stop" in proxy2
        assert "pause" in proxy2


class TestProcessData:
    def test_default_status(self):
        pd = ProcessData(name="p1")
        assert pd.status == ProcessStatus.INITIALIZING

    def test_add_and_get_queue(self):
        pd = ProcessData(name="p1")
        q = Queue()
        pd.add_queue("system", q)
        assert pd.get_queue("system") is q

    def test_add_and_get_event(self):
        pd = ProcessData(name="p1")
        e = Event()
        pd.add_event("stop", e)
        assert pd.get_event("stop") is e

    def test_queues_proxy(self):
        pd = ProcessData(name="p1")
        q = Queue()
        pd.add_queue("data", q)
        assert pd.queues.data is q

    def test_events_proxy(self):
        pd = ProcessData(name="p1")
        e = Event()
        pd.add_event("pause", e)
        assert pd.events.pause is e

    def test_update_status(self):
        pd = ProcessData(name="p1")
        pd.update_status(ProcessStatus.RUNNING)
        assert pd.status == ProcessStatus.RUNNING

    def test_update_metadata(self):
        pd = ProcessData(name="p1")
        pd.update_metadata(pid=1234)
        assert pd.metadata["pid"] == 1234

    def test_update_custom(self):
        pd = ProcessData(name="p1")
        pd.update_custom(foo="bar")
        assert pd.custom["foo"] == "bar"

    def test_to_dict(self):
        pd = ProcessData(name="p1")
        pd.add_queue("system", Queue())
        pd.add_event("stop", Event())
        d = pd.to_dict()
        assert d["name"] == "p1"
        assert d["status"] == "initializing"
        assert "system" in d["queue_types"]
        assert "stop" in d["event_names"]

    def test_to_dict_no_queue_refs(self):
        pd = ProcessData(name="p1")
        pd.add_queue("system", Queue())
        d = pd.to_dict()
        assert "system" not in d  # Queue объект не должен быть в dict

    def test_pickle_roundtrip_preserves_structure(self):
        """Pickle ProcessData без Queue/Event (Queue pickle только через Process spawn).
        Проверяем что структура и статус сохраняются."""
        pd = ProcessData(name="p1", status=ProcessStatus.RUNNING)
        pd.metadata["pid"] = 42
        pd.custom["foo"] = "bar"
        pd2 = pickle.loads(pickle.dumps(pd))
        assert pd2.name == "p1"
        assert pd2.status == ProcessStatus.RUNNING
        assert pd2.metadata["pid"] == 42
        assert pd2.custom["foo"] == "bar"

    def test_pickle_roundtrip_preserves_status_enum(self):
        pd = ProcessData(name="p1", status=ProcessStatus.RUNNING)
        pd2 = pickle.loads(pickle.dumps(pd))
        assert pd2.status == ProcessStatus.RUNNING

    def test_update_timestamp(self):
        pd = ProcessData(name="p1")
        old_ts = pd.updated_at
        time.sleep(0.01)
        pd.update_timestamp()
        assert pd.updated_at > old_ts
