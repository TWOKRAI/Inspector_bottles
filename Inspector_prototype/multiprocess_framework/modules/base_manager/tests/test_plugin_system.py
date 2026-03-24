"""
Тесты системы плагинов ObservableMixin.

Покрывает: встроенные плагины (Logger/Stats/Error), пользовательские плагины,
           register_plugin/unregister_plugin, has_plugin, get_plugin.
"""

import pytest
from typing import Any, Callable, Dict

from ..core.base_manager import BaseManager
from ..mixins.observable_mixin import ObservableMixin
from ..mixins.plugins.plugin_base import ObservablePlugin
from ..mixins.plugins.builtin_plugins import LoggerPlugin, StatsPlugin, ErrorPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockLogger:
    def __init__(self):
        self.logs = []

    def info(self, msg, **kw):
        self.logs.append(('info', msg))

    def debug(self, msg, **kw):
        self.logs.append(('debug', msg))


class MockStats:
    def __init__(self):
        self.data = []

    def record_metric(self, name, value=1, tags=None):
        self.data.append(('metric', name, value))


class MockErrorTracker:
    def __init__(self):
        self.errors = []

    def track_error(self, error, context=None):
        self.errors.append(error)


class PluggableManager(BaseManager, ObservableMixin):
    """Менеджер для тестов плагинов."""

    __test__ = False

    def __init__(self, managers=None, plugins=None, auto_proxy=False):
        BaseManager.__init__(self, "pluggable")
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config={k: True for k in (managers or {})},
            auto_proxy=auto_proxy,
            plugins=plugins,
        )

    def initialize(self):
        self.is_initialized = True
        return True

    def shutdown(self):
        self.is_initialized = False
        return True


# ---------------------------------------------------------------------------
# Custom plugin fixture
# ---------------------------------------------------------------------------

class NotificationPlugin(ObservablePlugin):
    """Пример пользовательского плагина для 'notifier' менеджера."""

    def get_manager_names(self):
        return ['notifier']

    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'notifier' not in managers:
            return

        def send_notification(message, channel='default'):
            return call_manager_func('notifier', 'send', message, channel)

        instance.send_notification = send_notification

    def create_private_methods(self, instance, call_manager_func):
        def _notify(self_inner, message):
            call_manager_func('notifier', 'send', message)

        import types
        instance._notify = types.MethodType(_notify, instance)


class MockNotifier:
    def __init__(self):
        self.sent = []

    def send(self, message, channel='default'):
        self.sent.append((message, channel))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPluginSystem:

    # ---- LoggerPlugin ----

    def test_logger_plugin_creates_proxy_methods(self):
        logger = MockLogger()
        m = PluggableManager(
            managers={'logger': logger},
            plugins=[LoggerPlugin()],
            auto_proxy=True,
        )
        assert hasattr(m, 'log_info')
        assert hasattr(m, 'log_debug')
        m.log_info("from plugin")
        assert logger.logs == [('info', 'from plugin')]

    def test_logger_plugin_no_manager_no_proxy(self):
        """LoggerPlugin не создаёт методы если 'logger' не зарегистрирован."""
        m = PluggableManager(
            managers={},
            plugins=[LoggerPlugin()],
            auto_proxy=True,
        )
        assert not hasattr(m, 'log_info')

    # ---- StatsPlugin ----

    def test_stats_plugin_with_stats_key(self):
        stats = MockStats()
        m = PluggableManager(
            managers={'stats': stats},
            plugins=[StatsPlugin()],
            auto_proxy=True,
        )
        assert hasattr(m, 'record_metric')
        m.record_metric("hits", value=7)
        assert stats.data == [('metric', 'hits', 7)]

    def test_stats_plugin_with_statistics_key(self):
        stats = MockStats()
        m = PluggableManager(
            managers={'statistics': stats},
            plugins=[StatsPlugin()],
            auto_proxy=True,
        )
        assert hasattr(m, 'record_metric')

    def test_stats_plugin_no_manager_no_proxy(self):
        m = PluggableManager(managers={}, plugins=[StatsPlugin()], auto_proxy=True)
        assert not hasattr(m, 'record_metric')

    # ---- ErrorPlugin ----

    def test_error_plugin_creates_proxy(self):
        tracker = MockErrorTracker()
        m = PluggableManager(
            managers={'error': tracker},
            plugins=[ErrorPlugin()],
            auto_proxy=True,
        )
        assert hasattr(m, 'track_error')
        err = Exception("test")
        m.track_error(err)
        assert err in tracker.errors

    # ---- Custom plugin ----

    def test_custom_plugin_register_at_init(self):
        notifier = MockNotifier()
        m = PluggableManager(
            managers={'notifier': notifier},
            plugins=[NotificationPlugin()],
            auto_proxy=True,
        )
        assert hasattr(m, 'send_notification')
        m.send_notification("hello", channel="email")
        assert ('hello', 'email') in notifier.sent

    def test_register_plugin_after_init(self):
        notifier = MockNotifier()
        m = PluggableManager(managers={'notifier': notifier}, auto_proxy=True)
        m.register_plugin(NotificationPlugin(), name='notification')
        assert m.has_plugin('notification')
        assert hasattr(m, 'send_notification')

    def test_unregister_plugin(self):
        m = PluggableManager()
        m.register_plugin(NotificationPlugin(), name='notification')
        assert m.has_plugin('notification')
        m.unregister_plugin('notification')
        assert not m.has_plugin('notification')

    def test_get_plugin_returns_instance(self):
        plugin = NotificationPlugin()
        m = PluggableManager()
        m.register_plugin(plugin, name='notification')
        assert m.get_plugin('notification') is plugin

    def test_broken_plugin_does_not_crash_init(self):
        """Плагин, вызывающий исключение, не должен ронять __init__."""

        class BrokenPlugin(ObservablePlugin):
            def get_manager_names(self):
                return ['x']

            def create_proxy_methods(self, instance, managers, call_manager_func):
                raise RuntimeError("broken plugin")

        m = PluggableManager(managers={}, plugins=[BrokenPlugin()], auto_proxy=True)
        assert m is not None  # не упал
