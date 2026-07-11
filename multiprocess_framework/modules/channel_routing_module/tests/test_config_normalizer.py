# -*- coding: utf-8 -*-
"""Характеризационные тесты normalize_config (CRM, база нормализатора D1).

Фиксируют ТЕКУЩЕЕ поведение публичной normalize_config() ДО консолидации с
LoggerCore._resolve_log_config / ErrorManager._normalize_error_config
(constructor-master Ф5-добор, задача C4/D1). См. DECISIONS.md ADR-CRM-008.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.config_normalizer import normalize_config


class TestNormalizeConfigShapes:
    """None | dict | build() — три поддерживаемых формы (docstring normalize_config)."""

    def test_none_returns_empty_dict(self) -> None:
        assert normalize_config(None) == {}

    def test_none_returns_default(self) -> None:
        default = {"level": "INFO"}
        assert normalize_config(None, default=default) == default

    def test_dict_passthrough(self) -> None:
        cfg = {"level": "INFO"}
        assert normalize_config(cfg) is cfg

    def test_build_tuple_convention(self) -> None:
        class Register:
            def build(self) -> tuple[str, Dict[str, Any]]:
                return ("RouterManager", {"send_queue_size": 512})

        assert normalize_config(Register()) == {"send_queue_size": 512}

    def test_build_returns_plain_dict(self) -> None:
        class BuildsDict:
            def build(self) -> Dict[str, Any]:
                return {"a": 1}

        assert normalize_config(BuildsDict()) == {"a": 1}

    def test_build_tuple_with_non_dict_payload_falls_back_to_default(self) -> None:
        class BadRegister:
            def build(self) -> tuple[str, Any]:
                return ("Name", "not-a-dict")

        default = {"fallback": True}
        assert normalize_config(BadRegister(), default=default) == default

    def test_build_raising_falls_back_to_default(self) -> None:
        class Boom:
            def build(self) -> Dict[str, Any]:
                raise RuntimeError("boom")

        default = {"fallback": True}
        assert normalize_config(Boom(), default=default) == default

    def test_unsupported_type_falls_back_to_default(self) -> None:
        default = {"fallback": True}
        assert normalize_config(123, default=default) == default

    def test_unsupported_type_no_default_returns_empty_dict(self) -> None:
        assert normalize_config(123) == {}
