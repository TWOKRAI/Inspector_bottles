# -*- coding: utf-8 -*-
"""Тесты inspector_registry — DI-шов + fail-loud fallback (C6 b, Fable HIGH-1).

Дефект: при незарегистрированной фабрике build_inspector молча отдавал PassThrough,
игнорируя явный inspector-конфиг (mode=join/fanin) — items летели без корреляции, ни
строки в логе. Прецедент: плагины из Services.* (phone_sketch) не триггерят self-register
пакета Plugins.*. Fix: явный конфиг без фабрики → RuntimeError (fail-loud); пустой конфиг
→ PassThrough + log_info.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.generic import inspector_registry
from multiprocess_framework.modules.process_module.generic.inspector_registry import (
    PassThroughInspector,
)


class TestFailLoudWithoutFactory:
    """Фабрика не зарегистрирована (_factory is None)."""

    def test_raises_when_inspector_config_set(self, monkeypatch):
        """Явный inspector-конфиг + нет фабрики → RuntimeError (не молчаливый PassThrough)."""
        monkeypatch.setattr(inspector_registry, "_factory", None)
        with pytest.raises(RuntimeError, match="зарегистрирована"):
            inspector_registry.build_inspector({"inspector": {"mode": "join"}})

    def test_raises_when_fanin_mode_set(self, monkeypatch):
        monkeypatch.setattr(inspector_registry, "_factory", None)
        with pytest.raises(RuntimeError):
            inspector_registry.build_inspector({"inspector": {"mode": "fanin", "timeout_sec": 0.3}})

    def test_passthrough_fallback_when_empty_config(self, monkeypatch):
        """Пустой inspector-конфиг + нет фабрики → PassThrough + log_info (не тихо)."""
        monkeypatch.setattr(inspector_registry, "_factory", None)
        logs: list[str] = []
        insp = inspector_registry.build_inspector({}, log_info=logs.append)
        assert isinstance(insp, PassThroughInspector)
        assert any("PassThrough" in m for m in logs), "fallback должен логироваться"

    def test_passthrough_empty_inspector_dict(self, monkeypatch):
        """inspector: {} (присутствует, но пуст) — тоже fallback, не raise."""
        monkeypatch.setattr(inspector_registry, "_factory", None)
        insp = inspector_registry.build_inspector({"inspector": {}}, log_info=lambda m: None)
        assert isinstance(insp, PassThroughInspector)


class TestWithFactory:
    """С зарегистрированной фабрикой (реальный путь) — делегирует, не падает."""

    def test_delegates_to_factory(self, monkeypatch):
        captured = {}

        def fake_factory(app_cfg, **kw):
            captured["cfg"] = app_cfg
            return PassThroughInspector()

        monkeypatch.setattr(inspector_registry, "_factory", fake_factory)
        inspector_registry.build_inspector({"inspector": {"mode": "join"}})
        assert captured["cfg"] == {"inspector": {"mode": "join"}}
