"""
Тесты для core/shared_resources_manager.py.

Ключевые сценарии:
- register_process() — единая точка регистрации
- Pickle/unpickle — Queue/Event сохраняются
- reinitialize_in_child() — восстановление после unpickle
- Properties — доступ к внутренним менеджерам
"""

import pickle
import pytest

from ..core.shared_resources_manager import SharedResourcesManager


@pytest.fixture
def srm():
    s = SharedResourcesManager()
    s.initialize()
    return s


BASIC_CONFIG = {
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
}


def _srm_worker(shared_resources, result_q):
    """Модульная функция для Process (local functions не pickle-able на Windows spawn)."""
    shared_resources.reinitialize_in_child()
    msg = shared_resources.get_process_data("p1").get_queue("system").get(timeout=2.0)
    result_q.put(msg)


class TestSRMInit:
    def test_initialize_returns_true(self):
        s = SharedResourcesManager()
        assert s.initialize() is True

    def test_properties_available(self, srm):
        assert srm.config_store is not None
        assert srm.process_state_registry is not None
        assert srm.queue_registry is not None
        assert srm.event_manager is not None
        assert srm.memory_manager is not None


class TestRegisterProcess:
    def test_register_creates_process_data(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        pd = srm.get_process_data("p1")
        assert pd is not None
        assert pd.name == "p1"

    def test_register_stores_config(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        cfg = srm.get_process_config("p1")
        assert cfg is not None
        assert "queues" in cfg

    def test_register_creates_queues(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        pd = srm.get_process_data("p1")
        assert pd.get_queue("system") is not None
        assert pd.get_queue("data") is not None

    def test_register_creates_stop_event(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        pd = srm.get_process_data("p1")
        assert pd.get_event("stop") is not None
        assert pd.get_event("pause") is not None

    def test_register_multiple_processes(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        srm.register_process("p2", BASIC_CONFIG)
        assert set(srm.get_process_names()) == {"p1", "p2"}

    def test_get_process_config_returns_copy(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        cfg = srm.get_process_config("p1")
        cfg["injected"] = True
        assert "injected" not in srm.get_process_config("p1")


def _srm_without_queues():
    """SRM без Queue/Event — для тестирования pickle в unit-тестах.
    Queue/Event pickle тестируется через реальный multiprocessing.Process (интеграционный тест).
    """
    s = SharedResourcesManager()
    s.initialize()
    # Регистрируем процесс без очередей и событий
    s._config_store.store("p1", BASIC_CONFIG)
    s._process_state_registry.register_process("p1")
    return s


class TestPickleRoundtrip:
    def test_pickle_preserves_process_names(self):
        """Pickle SRM без Queue/Event — проверяем структуру."""
        srm = _srm_without_queues()
        srm2 = pickle.loads(pickle.dumps(srm))
        assert "p1" in srm2.get_process_names()

    def test_pickle_preserves_config(self):
        srm = _srm_without_queues()
        srm2 = pickle.loads(pickle.dumps(srm))
        cfg = srm2.get_process_config("p1")
        assert cfg is not None
        assert "queues" in cfg

    def test_pickle_preserves_metadata(self):
        """Метаданные ProcessData сохраняются через pickle."""
        srm = _srm_without_queues()
        srm._process_state_registry.update_state("p1", metadata={"pid": 42})
        srm2 = pickle.loads(pickle.dumps(srm))
        pd = srm2.get_process_data("p1")
        assert pd.metadata["pid"] == 42

    def test_pickle_event_manager_has_no_queue(self, srm):
        """После pickle EventManager._event_queue должен быть None.
        Используем srm без Queue (EventManager._event_queue исключается в __getstate__)."""
        # Создаём SRM без register_process (нет Queue в PSR)
        s = SharedResourcesManager()
        s.initialize()
        srm2 = pickle.loads(pickle.dumps(s))
        assert srm2.event_manager._event_queue is None

    def test_pickle_event_manager_has_no_subscribers(self, srm):
        s = SharedResourcesManager()
        s.initialize()
        srm2 = pickle.loads(pickle.dumps(s))
        assert srm2.event_manager._subscribers == {}

    def test_queue_ipc_via_process(self, srm):
        """Интеграционный тест: Queue работает между процессами через SRM."""
        import multiprocessing as mp

        srm.register_process("p1", BASIC_CONFIG)
        q = srm.get_process_data("p1").get_queue("system")
        q.put("hello_from_parent")

        result_q = mp.Queue()
        p = mp.Process(target=_srm_worker, args=(srm, result_q))
        p.start()
        p.join(timeout=5)
        assert p.exitcode == 0
        assert result_q.get(timeout=1.0) == "hello_from_parent"


class TestReinitializeInChild:
    def test_reinitialize_restores_event_manager(self):
        """reinitialize_in_child() пересоздаёт EventManager ресурсы."""
        s = SharedResourcesManager()
        s.initialize()
        srm2 = pickle.loads(pickle.dumps(s))
        assert srm2.reinitialize_in_child() is True
        assert srm2.event_manager._event_queue is not None
        assert srm2.event_manager._new_event_event is not None

    def test_reinitialize_allows_emit(self):
        s = SharedResourcesManager()
        s.initialize()
        srm2 = pickle.loads(pickle.dumps(s))
        srm2.reinitialize_in_child()
        from ..types import EventType

        result = srm2.event_manager.emit_event(EventType.CONFIG_UPDATED)
        assert result is True


class TestDynamicAccess:
    def test_attribute_access_returns_process_data(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        pd = srm.p1
        assert pd.name == "p1"

    def test_attribute_access_missing_raises(self, srm):
        with pytest.raises(AttributeError):
            _ = srm.nonexistent_process


class TestConvenienceAccessors:
    def test_get_process_queue(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        q = srm.get_process_queue("p1", "system")
        assert q is not None

    def test_get_process_event(self, srm):
        srm.register_process("p1", BASIC_CONFIG)
        e = srm.get_process_event("p1", "stop")
        assert e is not None


class TestUnregisterProcess:
    """unregister_process — единая точка снятия процесса (ADR-SRM-009).

    Симметрия к register_process: SHM + запись PSR (очереди/события/метаданные)
    + конфиг ConfigStore. release_process_memory больше НЕ трогает PSR —
    контракт сужен до «только память»
    (Task 1.4 plans/2026-07-04_topology-switch-hardening.md).
    """

    def test_unregister_removes_psr_queues_events_and_config(self, srm):
        """После unregister в PSR нет ни очередей, ни событий, ни конфига."""
        srm.register_process("p1", BASIC_CONFIG)
        psr = srm.process_state_registry
        assert psr.has_process("p1")
        assert psr.get_queue("p1", "system") is not None
        assert psr.get_event("p1", "stop") is not None
        assert srm.get_process_config("p1") is not None

        assert srm.unregister_process("p1") is True

        assert not psr.has_process("p1")
        assert psr.get_queue("p1", "system") is None
        assert psr.get_event("p1", "stop") is None
        assert srm.get_process_config("p1") is None

    def test_unregister_unknown_is_idempotent(self, srm):
        """Снятие незарегистрированного имени — no-op, True."""
        assert srm.unregister_process("ghost") is True

    def test_release_process_memory_does_not_unregister_psr(self, srm):
        """Контракт сужен: release_process_memory — только память, запись PSR живёт."""
        srm.register_process("p1", BASIC_CONFIG)

        srm.memory_manager.release_process_memory("p1")

        assert srm.process_state_registry.has_process("p1")
        assert srm.process_state_registry.get_queue("p1", "system") is not None

    def test_reregister_after_unregister_creates_fresh_queues(self, srm):
        """Снятие → повторная регистрация того же имени даёт свежие очереди."""
        srm.register_process("p1", BASIC_CONFIG)
        q_old = srm.process_state_registry.get_queue("p1", "system")

        srm.unregister_process("p1")
        srm.register_process("p1", BASIC_CONFIG)

        q_new = srm.process_state_registry.get_queue("p1", "system")
        assert q_new is not None
        assert q_new is not q_old
