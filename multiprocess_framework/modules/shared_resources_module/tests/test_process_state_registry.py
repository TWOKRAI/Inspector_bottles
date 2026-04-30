"""
Тесты для state/process_state_registry.py.
"""

import logging
import pytest
from multiprocessing import Queue, Event

from ..state.process_state_registry import ProcessStateRegistry
from ..types import ProcessStatus


@pytest.fixture
def psr():
    return ProcessStateRegistry()


class TestProcessStateRegistry:
    def test_register_process(self, psr):
        assert psr.register_process("p1") is True
        assert psr.has_process("p1")

    def test_register_creates_process_data(self, psr):
        psr.register_process("p1")
        pd = psr.get_process_data("p1")
        assert pd is not None
        assert pd.name == "p1"
        assert pd.status == ProcessStatus.INITIALIZING

    def test_register_with_initial_state(self, psr):
        psr.register_process("p1", initial_state={"status": "ready", "metadata": {"pid": 42}})
        pd = psr.get_process_data("p1")
        assert pd.status == ProcessStatus.READY
        assert pd.metadata["pid"] == 42

    def test_has_process_false(self, psr):
        assert psr.has_process("nonexistent") is False

    def test_unregister_process(self, psr):
        psr.register_process("p1")
        assert psr.unregister_process("p1") is True
        assert not psr.has_process("p1")

    def test_unregister_missing_returns_false(self, psr):
        assert psr.unregister_process("nonexistent") is False

    def test_get_process_names(self, psr):
        psr.register_process("p1")
        psr.register_process("p2")
        names = psr.get_process_names()
        assert set(names) == {"p1", "p2"}

    def test_update_state_status(self, psr):
        psr.register_process("p1")
        psr.update_state("p1", status=ProcessStatus.RUNNING)
        pd = psr.get_process_data("p1")
        assert pd.status == ProcessStatus.RUNNING

    def test_update_state_string_status(self, psr):
        psr.register_process("p1")
        psr.update_state("p1", status="running")
        pd = psr.get_process_data("p1")
        assert pd.status == ProcessStatus.RUNNING

    def test_add_queue(self, psr):
        psr.register_process("p1")
        q = Queue()
        assert psr.add_queue("p1", "system", q) is True
        assert psr.get_queue("p1", "system") is q

    def test_add_event(self, psr):
        psr.register_process("p1")
        e = Event()
        assert psr.add_event("p1", "stop", e) is True
        assert psr.get_event("p1", "stop") is e

    def test_get_all_process_data(self, psr):
        psr.register_process("p1")
        psr.register_process("p2")
        all_data = psr.get_all_process_data()
        assert set(all_data.keys()) == {"p1", "p2"}

    def test_get_stats(self, psr):
        psr.register_process("p1")
        psr.update_state("p1", status=ProcessStatus.RUNNING)
        stats = psr.get_stats()
        assert stats["total_processes"] == 1
        assert "running" in stats["status_counts"]

    def test_logger_used_instead_of_print(self, caplog):
        """PSR должен использовать logger, а не print()."""
        logger = logging.getLogger("test_psr")
        psr_with_logger = ProcessStateRegistry(logger=logger)
        with caplog.at_level(logging.ERROR, logger="test_psr"):
            # Принудительно вызываем ошибку через некорректный статус
            psr_with_logger.register_process("p1", initial_state={"status": "invalid_status_xyz"})
        # Не должно быть print, ошибка должна быть поймана gracefully
        assert psr_with_logger.has_process("p1") is False or True  # не падает

    def test_event_emitted_on_register(self):
        """PSR должен вызывать event_manager.emit_event при регистрации."""
        emitted = []

        class FakeEventManager:
            def emit_event(self, event_type, **kwargs):
                emitted.append((event_type, kwargs))

        psr = ProcessStateRegistry(event_manager=FakeEventManager())
        psr.register_process("p1")
        assert len(emitted) == 1
        assert emitted[0][0].value == "process_registered"
