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
        em = ErrorManager(config={
            "app_name": "test_errors",
            "default_level": "ERROR",
        })
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
