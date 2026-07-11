# -*- coding: utf-8 -*-
"""Характеризационные тесты ErrorManager._normalize_error_config (D1).

Фиксируют ТЕКУЩЕЕ поведение резолвера конфига ДО консолидации с базовым
normalize_config() из channel_routing_module (constructor-master Ф5-добор,
задача C4/D1). См. DECISIONS.md ADR-CRM-008 в channel_routing_module.

Проверяем через публичный вход (ErrorManager) — не завязываемся на приватную
реализацию, которая уйдёт после рефакторинга.
"""

from __future__ import annotations


import pytest

from ..core.error_manager import ErrorManager
from ..configs.error_manager_config import ErrorManagerConfig
from ...logger_module.core.log_config import LoggerManagerConfig


class TestErrorConfigResolution:
    def test_none_uses_defaults(self) -> None:
        em = ErrorManager(config=None)
        assert em.manager_name == "ErrorManager"
        assert em.app_name == "errors"
        assert em.config.default_level == "WARNING"

    def test_dict_expands_severity_channels(self) -> None:
        em = ErrorManager(config={"app_name": "test_errors", "default_level": "ERROR"})
        assert em.app_name == "test_errors"
        assert "errors_file" in em.config.channels
        assert "critical_file" in em.config.channels

    def test_error_manager_config_instance(self) -> None:
        cfg = ErrorManagerConfig(app_name="from_register")
        em = ErrorManager(config=cfg)
        assert em.app_name == "from_register"

    def test_logger_manager_config_instance_passthrough(self) -> None:
        """isinstance-шорткат: готовый LoggerManagerConfig не разворачивается через build()."""
        cfg = LoggerManagerConfig(app_name="typed_app")
        em = ErrorManager(config=cfg)
        assert em.config is cfg
        assert em.app_name == "typed_app"

    def test_build_object_convention(self) -> None:
        class MockConfig:
            def build(self):
                return ("CustomName", {"app_name": "custom", "default_level": "ERROR"})

        em = ErrorManager(config=MockConfig())
        assert em.manager_name == "CustomName"
        assert em.app_name == "custom"

    def test_build_object_include_stacktrace_attr_override(self) -> None:
        class MockConfig:
            include_stacktrace = False

            def build(self):
                return ("CustomName", {"app_name": "custom"})

        em = ErrorManager(config=MockConfig())
        assert em._include_stacktrace is False

    def test_invalid_config_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="config must be dict"):
            ErrorManager(config=123)
