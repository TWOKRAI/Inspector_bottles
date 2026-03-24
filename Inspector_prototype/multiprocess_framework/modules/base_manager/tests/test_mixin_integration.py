"""
Интеграционные тесты ObservableMixin.

Проверяет совместную работу: multiple managers, динамическое подключение,
переключение состояния, get_available_methods.
"""

import pytest
from ..core.base_manager import BaseManager
from ..mixins.observable_mixin import ObservableMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockLogger:
    def __init__(self):
        self.logs = []

    def info(self, msg, **kw):
        self.logs.append(('info', msg))

    def warning(self, msg, **kw):
        self.logs.append(('warning', msg))

    def error(self, msg, **kw):
        self.logs.append(('error', msg))

    def debug(self, msg, **kw):
        self.logs.append(('debug', msg))


class MockStats:
    def __init__(self):
        self.data = []

    def record_metric(self, name, value=1, tags=None):
        self.data.append(('metric', name, value))

    def record_timing(self, name, duration, tags=None):
        self.data.append(('timing', name, duration))

    def increment(self, name, tags=None):
        self.data.append(('inc', name))

    def gauge(self, name, value, tags=None):
        self.data.append(('gauge', name, value))


class MultiManager(BaseManager, ObservableMixin):
    """Менеджер с несколькими зарегистрированными сервисами."""

    __test__ = False

    def __init__(self, logger=None, stats=None, auto_proxy=False):
        BaseManager.__init__(self, "multi_manager")
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['stats'] = stats
        ObservableMixin.__init__(
            self,
            managers=managers,
            config={k: True for k in managers},
            auto_proxy=auto_proxy,
        )

    def initialize(self):
        self.is_initialized = True
        return True

    def shutdown(self):
        self.is_initialized = False
        return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMixinIntegration:

    def test_multiple_managers_independent(self):
        logger = MockLogger()
        stats = MockStats()
        m = MultiManager(logger=logger, stats=stats)

        m._log_info("msg")
        m._record_metric("op", value=3)

        assert logger.logs == [('info', 'msg')]
        assert stats.data == [('metric', 'op', 3)]

    def test_disable_one_manager_does_not_affect_other(self):
        logger = MockLogger()
        stats = MockStats()
        m = MultiManager(logger=logger, stats=stats)

        m.disable('logger')
        m._log_info("suppressed")
        m._record_metric("still_works")

        assert logger.logs == []
        assert stats.data == [('metric', 'still_works', 1)]

    def test_dynamic_register_and_call(self):
        m = MultiManager()
        logger = MockLogger()
        m.register_manager('logger', logger)
        m._log_info("dynamic")
        assert logger.logs == [('info', 'dynamic')]

    def test_auto_proxy_stats_methods(self):
        stats = MockStats()
        m = MultiManager(stats=stats, auto_proxy=True)

        m.record_metric("clicks", value=10)
        m.increment("views")
        m.record_timing("query", 0.1)

        assert ('metric', 'clicks', 10) in stats.data
        assert ('inc', 'views') in stats.data
        assert ('timing', 'query', 0.1) in stats.data

    def test_get_available_methods_includes_managers(self):
        logger = MockLogger()
        m = MultiManager(logger=logger)
        info = m.get_available_methods()
        assert 'logger' in info['managers']

    def test_context_restores_state_after_exception(self):
        logger = MockLogger()
        m = MultiManager(logger=logger)

        try:
            with m.context('logger', enabled=False):
                raise RuntimeError("test")
        except RuntimeError:
            pass

        m._log_info("should work after exception in context")
        assert logger.logs == [('info', 'should work after exception in context')]

    def test_get_state_snapshot(self):
        logger = MockLogger()
        m = MultiManager(logger=logger)
        state = m.get_state()

        assert 'managers' in state
        assert 'logger' in state['managers']
        assert 'enabled' in state
        assert 'plugins' in state

    def test_unregister_and_reregister(self):
        logger1 = MockLogger()
        logger2 = MockLogger()
        m = MultiManager(logger=logger1)

        m._log_info("to logger1")
        m.unregister_manager('logger')
        m._log_info("no logger")
        m.register_manager('logger', logger2)
        m._log_info("to logger2")

        assert logger1.logs == [('info', 'to logger1')]
        assert logger2.logs == [('info', 'to logger2')]
