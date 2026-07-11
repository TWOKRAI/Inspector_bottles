# -*- coding: utf-8 -*-
"""Характеризационные тесты LoggerCore._resolve_log_config (D1).

Фиксируют ТЕКУЩЕЕ поведение резолвера конфига ДО консолидации с базовым
normalize_config() из channel_routing_module (constructor-master Ф5-добор,
задача C4/D1). См. DECISIONS.md ADR-CRM-008 в channel_routing_module.

Проверяем через публичный вход (LoggerManager) — не завязываемся на приватную
реализацию, которая уйдёт после рефакторинга.
"""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.log_config import LoggerManagerConfig


class TestLoggerConfigResolution:
    def test_none_uses_defaults(self) -> None:
        mgr = LoggerManager(config=None)
        assert isinstance(mgr.config, LoggerManagerConfig)
        assert mgr.config.app_name == "unknown_app"

    def test_empty_dict_uses_defaults(self) -> None:
        mgr = LoggerManager(config={})
        assert mgr.config.app_name == "unknown_app"

    def test_dict_is_validated(self) -> None:
        mgr = LoggerManager(config={"app_name": "custom_app"})
        assert mgr.config.app_name == "custom_app"

    def test_already_typed_instance_passthrough(self) -> None:
        """isinstance-шорткат: готовый LoggerManagerConfig не идёт через build()/model_validate заново."""
        cfg = LoggerManagerConfig(app_name="typed_app")
        mgr = LoggerManager(config=cfg)
        assert mgr.config is cfg

    def test_build_tuple_convention(self) -> None:
        class Register:
            def build(self) -> tuple[str, Dict[str, Any]]:
                return ("Ignored", {"app_name": "from_build"})

        mgr = LoggerManager(config=Register())
        assert mgr.config.app_name == "from_build"

    def test_build_returns_plain_dict(self) -> None:
        class BuildsDict:
            def build(self) -> Dict[str, Any]:
                return {"app_name": "from_dict_build"}

        mgr = LoggerManager(config=BuildsDict())
        assert mgr.config.app_name == "from_dict_build"

    def test_build_tuple_with_non_dict_payload_falls_back_to_defaults(self) -> None:
        class BadRegister:
            def build(self) -> tuple[str, Any]:
                return ("Name", "not-a-dict")

        mgr = LoggerManager(config=BadRegister())
        assert mgr.config.app_name == "unknown_app"

    def test_unsupported_type_falls_back_to_defaults(self) -> None:
        """Нет build()/dict — тихий fallback на дефолтный LoggerManagerConfig (без исключения)."""
        mgr = LoggerManager(config=123)
        assert mgr.config.app_name == "unknown_app"
