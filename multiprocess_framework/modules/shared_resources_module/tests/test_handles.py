"""Тесты для Handle API — ProcessHandle, QueueHandle, EventHandle."""

import pytest

from ..core.shared_resources_manager import SharedResourcesManager
from ..handles import ProcessHandle
from ..types import ProcessStatus


BASIC_CONFIG = {
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "events": ["custom_event"],
}


@pytest.fixture
def srm():
    s = SharedResourcesManager()
    s.initialize()
    s.register_process("worker", BASIC_CONFIG)
    return s


class TestProcessHandle:
    def test_process_returns_handle(self, srm):
        handle = srm.for_process("worker")
        assert isinstance(handle, ProcessHandle)
        assert handle.name == "worker"

    def test_process_missing_raises_key_error(self, srm):
        with pytest.raises(KeyError, match="not registered"):
            srm.for_process("not_registered")

    def test_handle_status(self, srm):
        handle = srm.for_process("worker")
        assert handle.status == ProcessStatus.INITIALIZING

    def test_handle_config(self, srm):
        handle = srm.for_process("worker")
        cfg = handle.config
        assert cfg is not None
        assert "queues" in cfg

    def test_handle_data(self, srm):
        handle = srm.for_process("worker")
        assert handle.data is not None
        assert handle.data.name == "worker"

    def test_handle_metadata(self, srm):
        handle = srm.for_process("worker")
        assert isinstance(handle.metadata, dict)


class TestQueueHandle:
    def test_send_and_receive(self, srm):
        handle = srm.for_process("worker")
        qh = handle.queue("system")
        assert qh.send({"cmd": "test"})
        msg = qh.receive(timeout=1.0)
        assert msg == {"cmd": "test"}

    def test_receive_empty_returns_none(self, srm):
        handle = srm.for_process("worker")
        qh = handle.queue("system")
        assert qh.receive() is None

    def test_size(self, srm):
        handle = srm.for_process("worker")
        qh = handle.queue("system")
        qh.send("msg1")
        qh.send("msg2")
        # qsize() не гарантирован на всех платформах; проверяем доставку
        assert qh.receive(timeout=1.0) == "msg1"
        assert qh.receive(timeout=1.0) == "msg2"

    def test_missing_queue_send_returns_false(self, srm):
        handle = srm.for_process("worker")
        qh = handle.queue("nonexistent")
        assert qh.send("test") is False

    def test_raw_returns_queue(self, srm):
        handle = srm.for_process("worker")
        qh = handle.queue("system")
        assert qh.raw is not None
        assert hasattr(qh.raw, "put") and hasattr(qh.raw, "get")

    def test_repr(self, srm):
        handle = srm.for_process("worker")
        qh = handle.queue("system")
        assert "worker" in repr(qh)
        assert "system" in repr(qh)


class TestEventHandle:
    def test_set_and_is_set(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("stop")
        assert not eh.is_set
        eh.set()
        assert eh.is_set

    def test_clear(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("stop")
        eh.set()
        eh.clear()
        assert not eh.is_set

    def test_wait_returns_true_when_set(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("stop")
        eh.set()
        assert eh.wait(timeout=0.1) is True

    def test_wait_returns_false_on_timeout(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("stop")
        assert eh.wait(timeout=0.01) is False

    def test_custom_event(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("custom_event")
        assert eh.raw is not None
        eh.set()
        assert eh.is_set

    def test_missing_event_is_safe(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("nonexistent")
        assert eh.raw is None
        assert eh.is_set is False
        eh.set()
        assert eh.wait(timeout=0.01) is False

    def test_raw_returns_event(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("stop")
        assert eh.raw is not None
        assert hasattr(eh.raw, "set") and hasattr(eh.raw, "wait")

    def test_repr(self, srm):
        handle = srm.for_process("worker")
        eh = handle.event("stop")
        assert "worker" in repr(eh)
        assert "stop" in repr(eh)


class TestSRMHighLevel:
    def test_has_process_true(self, srm):
        assert srm.has_process("worker") is True

    def test_has_process_false(self, srm):
        assert srm.has_process("nonexistent") is False

    def test_broadcast(self, srm):
        srm.register_process("worker2", BASIC_CONFIG)
        sent = srm.broadcast({"cmd": "stop_all"})
        assert sent == 2

    def test_broadcast_with_exclude(self, srm):
        srm.register_process("worker2", BASIC_CONFIG)
        sent = srm.broadcast({"cmd": "stop"}, exclude="worker")
        assert sent == 1

    def test_get_all_statuses(self, srm):
        statuses = srm.get_all_statuses()
        assert "worker" in statuses
        assert statuses["worker"] == ProcessStatus.INITIALIZING


def _handle_ipc_worker(shared_resources, result_q):
    """Worker для интеграционного теста Handle API через multiprocessing.Process."""
    shared_resources.reinitialize_in_child()
    handle = shared_resources.for_process("p1")
    # Прочитать сообщение через Handle API
    msg = handle.queue("system").receive(timeout=2.0)
    result_q.put(msg)
    # Проверить event через Handle API
    result_q.put(handle.event("stop").is_set)


class TestHandlePickleRoundtrip:
    """Интеграционный тест: Handle API работает после pickle/unpickle SRM.

    Queue/Event в Python 3.14+ можно pickle только через multiprocessing.Process
    (spawn context), не через прямой pickle.dumps(). Поэтому используем
    реальный Process для IPC-теста, а для структуры — SRM без Queue.
    """

    def test_pickle_preserves_has_process(self):
        """has_process() и for_process() работают после pickle (без Queue)."""
        import pickle

        # SRM без register_process — без Queue/Event (pickle-safe)
        srm = SharedResourcesManager()
        srm.initialize()
        srm._config_store.store("cam", BASIC_CONFIG)
        srm._process_state_registry.register_process("cam")

        srm2 = pickle.loads(pickle.dumps(srm))
        srm2.reinitialize_in_child()

        assert srm2.has_process("cam") is True
        assert srm2.has_process("nonexistent") is False
        handle = srm2.for_process("cam")
        assert handle.name == "cam"
        assert handle.status == ProcessStatus.INITIALIZING
        assert handle.config is not None

    def test_handle_ipc_via_process(self):
        """Handle API через реальный multiprocessing.Process (Queue + Event)."""
        import multiprocessing as mp

        srm = SharedResourcesManager()
        srm.initialize()
        srm.register_process("p1", BASIC_CONFIG)

        # Положить сообщение и установить event через Handle API
        srm.for_process("p1").queue("system").send({"via": "handle"})
        srm.for_process("p1").event("stop").set()

        result_q = mp.Queue()
        p = mp.Process(target=_handle_ipc_worker, args=(srm, result_q))
        p.start()
        # Под нагрузкой полного прогона старт дочернего процесса на Windows
        # стабильно укладывается в ~5-10с, изолированно — <1с. Берём 15с с запасом.
        p.join(timeout=15)
        assert p.exitcode == 0

        msg = result_q.get(timeout=1.0)
        assert msg == {"via": "handle"}
        event_was_set = result_q.get(timeout=1.0)
        assert event_was_set is True
