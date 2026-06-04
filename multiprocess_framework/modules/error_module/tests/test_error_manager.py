# -*- coding: utf-8 -*-
"""Тесты ErrorManager."""

import pytest

from ..core.error_manager import ErrorManager
from ..configs.error_manager_config import ErrorManagerConfig


class TestErrorManager:
    """Тесты ErrorManager."""

    def test_init_with_none(self) -> None:
        """Инициализация с config=None использует дефолты.

        default_level=WARNING: ErrorManager ловит WARNING, ERROR, CRITICAL.
        """
        em = ErrorManager(config=None)
        assert em.app_name == "errors"
        assert em.config.default_level == "WARNING"

    def test_init_with_dict(self) -> None:
        """Инициализация с config=dict."""
        em = ErrorManager(
            config={
                "app_name": "test_errors",
                "default_level": "ERROR",
            }
        )
        assert em.app_name == "test_errors"

    def test_init_with_error_manager_config(self) -> None:
        """Инициализация с ErrorManagerConfig (build())."""
        config = ErrorManagerConfig(app_name="from_register")
        em = ErrorManager(config=config)

        assert em.app_name == "from_register"

    def test_init_with_build_object(self) -> None:
        """Инициализация с объектом, имеющим build()."""

        class MockConfig:
            def build(self):
                return ("CustomName", {"app_name": "custom", "default_level": "ERROR"})

        em = ErrorManager(config=MockConfig())
        assert em.manager_name == "CustomName"
        assert em.app_name == "custom"

    def test_log_exception(self) -> None:
        """log_exception() не падает."""
        em = ErrorManager(config=None)
        em.initialize()

        try:
            raise ValueError("test error")
        except ValueError as e:
            em.log_exception(e, message="Caught", module="test")

        em.shutdown()

    def test_invalid_config_raises(self) -> None:
        """Невалидный config вызывает TypeError."""
        with pytest.raises(TypeError, match="config must be dict"):
            ErrorManager(config=123)

    def test_get_stats_includes_level_routes(self) -> None:
        """get_stats() возвращает level_routes (маппинг level → channel)."""
        em = ErrorManager(config=None)
        em.initialize()
        stats = em.get_stats()
        em.shutdown()

        assert "level_routes" in stats
        assert isinstance(stats["level_routes"], dict)
        assert "include_stacktrace" in stats


class TestErrorReconfigure:
    """reconfigure: каналы пересобраны, severity-routes перестроены (Task 1.3)."""

    def test_level_routes_rebuilt_on_reconfigure(self) -> None:
        # Старт с дефолтом: есть critical/errors/warnings → отдельный route для WARNING.
        em = ErrorManager(config=None)
        em.initialize()
        before = em.get_stats()["level_routes"]
        assert before.get("WARNING") == "warnings_file"
        assert before.get("CRITICAL") == "critical_file"

        # Reconfigure БЕЗ warnings_file_path → warnings_file отсутствует,
        # WARNING должен упасть на errors_file.
        assert (
            em.reconfigure(
                {
                    "app_name": "errors2",
                    "critical_file_path": "logs/c2.log",
                    "error_file_path": "logs/e2.log",
                }
            )
            is True
        )

        after = em.get_stats()["level_routes"]
        assert after.get("WARNING") == "errors_file"
        assert after.get("ERROR") == "errors_file"
        assert after.get("CRITICAL") == "critical_file"
        em.shutdown()

    def test_include_stacktrace_updates(self) -> None:
        em = ErrorManager(config={"include_stacktrace": True})
        em.initialize()
        assert em._include_stacktrace is True

        assert em.reconfigure({"include_stacktrace": False}) is True
        assert em._include_stacktrace is False
        assert em.get_stats()["include_stacktrace"] is False
        em.shutdown()

    def test_reconfigure_empty_dict_uses_defaults(self) -> None:
        em = ErrorManager(config=None)
        em.initialize()
        # Пустой dict → expand даёт critical+errors → процесс не падает.
        assert em.reconfigure({}) is True
        routes = em.get_stats()["level_routes"]
        assert routes.get("ERROR") == "errors_file"
        em.shutdown()

    def test_reconfigure_before_initialize_does_not_raise(self) -> None:
        em = ErrorManager(config=None)
        # без initialize(): буфер не запущен
        assert em.reconfigure({"critical_file_path": "logs/c.log", "error_file_path": "logs/e.log"}) is True
