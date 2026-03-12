"""
Тесты ObservableMixin.

Покрывает: приватные методы, авто-прокси, enable/disable, context-менеджер,
           register/unregister manager, плагины, get_state, pickle-совместимость.
"""

import pickle
import pytest

from ..core.base_manager import BaseManager
from ..mixins.observable_mixin import ObservableMixin
from ..interfaces import IObservableMixin


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class MockLogger:
    """Мок-логгер: собирает вызовы в self.logs."""

    def __init__(self):
        self.logs = []

    def debug(self, msg, **kwargs):
        self.logs.append(('debug', msg))

    def info(self, msg, **kwargs):
        self.logs.append(('info', msg))

    def warning(self, msg, **kwargs):
        self.logs.append(('warning', msg))

    def error(self, msg, **kwargs):
        self.logs.append(('error', msg))

    def critical(self, msg, **kwargs):
        self.logs.append(('critical', msg))


class MockStats:
    """Мок-статистика: собирает вызовы в self.metrics."""

    def __init__(self):
        self.metrics = []

    def record_metric(self, name, value=1, tags=None):
        self.metrics.append(('record_metric', name, value))

    def increment(self, name, tags=None):
        self.metrics.append(('increment', name))

    def record_timing(self, name, duration, tags=None):
        self.metrics.append(('record_timing', name, duration))

    def gauge(self, name, value, tags=None):
        self.metrics.append(('gauge', name, value))


class MockErrorTracker:
    """Мок-трекер ошибок: собирает вызовы в self.errors."""

    def __init__(self):
        self.errors = []

    def track_error(self, error, context=None):
        self.errors.append(('track_error', error))

    def record_error(self, error, context=None):
        self.errors.append(('record_error', error))


class ObservableManager(BaseManager, ObservableMixin):
    """Тестовый менеджер — сочетание BaseManager + ObservableMixin."""

    __test__ = False  # Исключить из pytest-коллекции

    def __init__(
        self,
        name,
        logger=None,
        stats=None,
        error_tracker=None,
        auto_proxy=False,
        enable_decorators=False,
    ):
        BaseManager.__init__(self, name)

        managers = {}
        if logger is not None:
            managers['logger'] = logger
        if stats is not None:
            managers['stats'] = stats
        if error_tracker is not None:
            managers['error'] = error_tracker

        config = {k: True for k in managers}
        if enable_decorators:
            config['enable_decorators'] = True

        ObservableMixin.__init__(self, managers=managers, config=config, auto_proxy=auto_proxy)

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


# ---------------------------------------------------------------------------
# TestObservableMixin
# ---------------------------------------------------------------------------

class TestObservableMixin:

    # ---- Приватные методы (класс-level, всегда доступны) ----

    def test_private_log_info_calls_logger(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m._log_info("hello")
        assert logger.logs == [('info', 'hello')]

    def test_private_log_levels(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m._log_debug("d")
        m._log_warning("w")
        m._log_error("e")
        m._log_critical("c")
        assert ('debug', 'd') in logger.logs
        assert ('warning', 'w') in logger.logs
        assert ('error', 'e') in logger.logs
        assert ('critical', 'c') in logger.logs

    def test_private_log_without_logger_is_noop(self):
        m = ObservableManager("test")
        m._log_info("no logger registered")  # не должен падать

    def test_private_record_metric(self):
        stats = MockStats()
        m = ObservableManager("test", stats=stats)
        m._record_metric("ops.count", value=5)
        assert ('record_metric', 'ops.count', 5) in stats.metrics

    def test_private_record_timing(self):
        stats = MockStats()
        m = ObservableManager("test", stats=stats)
        m._record_timing("query.time", 0.025)
        assert ('record_timing', 'query.time', 0.025) in stats.metrics

    def test_private_track_error_via_error_manager(self):
        tracker = MockErrorTracker()
        m = ObservableManager("test", error_tracker=tracker)
        err = ValueError("oops")
        m._track_error(err)
        assert any(entry[1] is err for entry in tracker.errors)

    # ---- Auto-proxy ----

    def test_auto_proxy_creates_public_methods(self):
        logger = MockLogger()
        stats = MockStats()
        m = ObservableManager("test", logger=logger, stats=stats, auto_proxy=True)
        assert hasattr(m, 'log_info')
        assert hasattr(m, 'record_metric')

    def test_auto_proxy_log_info_works(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger, auto_proxy=True)
        m.log_info("via proxy")
        assert logger.logs == [('info', 'via proxy')]

    def test_auto_proxy_both_private_and_public(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger, auto_proxy=True)
        m._log_info("private")
        m.log_info("public")
        assert logger.logs == [('info', 'private'), ('info', 'public')]

    def test_no_auto_proxy_no_public_methods(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger, auto_proxy=False)
        assert not hasattr(m, 'log_info')

    # ---- Enable / Disable ----

    def test_disable_stops_logging(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m._log_info("before disable")
        m.disable('logger')
        m._log_info("after disable")
        assert len(logger.logs) == 1

    def test_enable_restores_logging(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m.disable('logger')
        m.enable('logger')
        m._log_info("after enable")
        assert len(logger.logs) == 1

    def test_is_enabled(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        assert m.is_enabled('logger') is True
        m.disable('logger')
        assert m.is_enabled('logger') is False

    def test_get_enabled_managers(self):
        logger = MockLogger()
        stats = MockStats()
        m = ObservableManager("test", logger=logger, stats=stats)
        enabled = m.get_enabled_managers()
        assert 'logger' in enabled
        assert 'stats' in enabled

    # ---- Context manager ----

    def test_context_temporarily_disables(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        with m.context('logger', enabled=False):
            m._log_info("suppressed")
        m._log_info("after context")
        assert logger.logs == [('info', 'after context')]

    # ---- Register / Unregister ----

    def test_register_manager_after_init(self):
        m = ObservableManager("test")
        logger = MockLogger()
        m.register_manager('logger', logger)
        assert m.has_manager('logger')
        m._log_info("via late-registered logger")
        assert logger.logs == [('info', 'via late-registered logger')]

    def test_unregister_manager(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m.unregister_manager('logger')
        assert not m.has_manager('logger')
        m._log_info("should be silent")
        assert logger.logs == []

    def test_register_manager_updates_proxy(self):
        m = ObservableManager("test", auto_proxy=True)
        assert not hasattr(m, 'log_info')
        logger = MockLogger()
        m.register_manager('logger', logger)
        assert hasattr(m, 'log_info')

    # ---- Get state / config ----

    def test_get_state_contains_managers(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        state = m.get_state()
        assert 'managers' in state
        assert 'logger' in state['managers']
        assert 'plugins' in state

    def test_update_config(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m.update_config({'logger': False})
        m._log_info("should be suppressed")
        assert logger.logs == []

    # ---- Isinstance ----

    def test_isinstance_iobservablemixin(self):
        m = ObservableManager("test")
        assert isinstance(m, IObservableMixin)

    # ---- Pickle ----

    def test_pickle_roundtrip_private_methods_survive(self):
        """После pickle/unpickle приватные методы (класс-level) не падают."""
        logger = MockLogger()
        m = ObservableManager("test", logger=logger)
        m.initialize()

        data = pickle.dumps(m)
        m2 = pickle.loads(data)

        assert m2.manager_name == "test"
        assert m2.is_initialized is True
        # _log_info — метод класса, не падает (просто возвращает None, т.к. _registry пустой)
        m2._log_info("after unpickle")

    def test_pickle_roundtrip_no_registry_means_silent_noop(self):
        """После unpickle все вызовы _log_* тихо возвращают None."""
        m = ObservableManager("test")
        m2 = pickle.loads(pickle.dumps(m))
        result = m2._call_manager('logger', 'info', 'test')
        assert result is None

    def test_pickle_roundtrip_auto_proxy_without_managers(self):
        """
        После unpickle proxy-методы (log_info, …) НЕ создаются,
        если managers не были восстановлены (они не picklable).

        Корректное поведение: публичные методы появляются только когда
        соответствующий менеджер реально зарегистрирован. После unpickle
        владелец должен заново вызвать register_manager() если нужно.
        """
        logger = MockLogger()
        m = ObservableManager("test", logger=logger, auto_proxy=True)
        assert hasattr(m, 'log_info')  # до pickle — метод есть

        m2 = pickle.loads(pickle.dumps(m))
        # После unpickle managers потеряны → log_info не существует
        assert not hasattr(m2, 'log_info')

        # Но после ручного register_manager — снова появится
        m2.register_manager('logger', MockLogger())
        assert hasattr(m2, 'log_info')

    # ---- Декораторы (опционально, skip если не поддерживаются) ----

    def test_decorator_logged(self):
        logger = MockLogger()
        m = ObservableManager("test", logger=logger, enable_decorators=True)

        if not hasattr(m, 'logged'):
            pytest.skip("Декораторы отключены")

        @m.logged(manager_name='logger', level='info')
        def fn():
            return "result"

        assert fn() == "result"
        assert len(logger.logs) >= 1

    def test_decorator_timed(self):
        stats = MockStats()
        m = ObservableManager("test", stats=stats, enable_decorators=True)

        if not hasattr(m, 'timed'):
            pytest.skip("Декораторы отключены")

        @m.timed(manager_name='stats', metric_name='fn.time')
        def fn():
            return "result"

        assert fn() == "result"
        assert len(stats.metrics) >= 1
