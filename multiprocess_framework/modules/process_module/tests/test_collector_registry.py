# -*- coding: utf-8 -*-
"""Тесты collector_registry — DI-шов + fail-loud fallback (C6 b, Fable HIGH-1).

Дефект: при незарегистрированной фабрике build_collector молча отдавал PassThrough,
игнорируя явная секция collector (mode=join/fanin) — items летели без корреляции, ни
строки в логе. Прецедент: плагины из Services.* (phone_sketch) не триггерят self-register
пакета Plugins.*. Fix: явный конфиг без фабрики → RuntimeError (fail-loud); пустой конфиг
→ PassThrough + log_info.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.generic import collector_registry
from multiprocess_framework.modules.process_module.generic.collector_registry import (
    PassThroughCollector,
)


class TestFailLoudWithoutFactory:
    """Фабрика не зарегистрирована (_factory is None)."""

    def test_raises_when_collector_config_set(self, monkeypatch):
        """Явная секция collector + нет фабрики → RuntimeError (не молчаливый PassThrough)."""
        monkeypatch.setattr(collector_registry, "_factory", None)
        with pytest.raises(RuntimeError, match="зарегистрирована"):
            collector_registry.build_collector({"collector": {"mode": "join"}})

    def test_raises_when_fanin_mode_set(self, monkeypatch):
        monkeypatch.setattr(collector_registry, "_factory", None)
        with pytest.raises(RuntimeError):
            collector_registry.build_collector({"collector": {"mode": "fanin", "timeout_sec": 0.3}})

    def test_passthrough_fallback_when_empty_config(self, monkeypatch):
        """Пустая секция collector + нет фабрики → PassThrough + log_info (не тихо)."""
        monkeypatch.setattr(collector_registry, "_factory", None)
        logs: list[str] = []
        insp = collector_registry.build_collector({}, log_info=logs.append)
        assert isinstance(insp, PassThroughCollector)
        assert any("PassThrough" in m for m in logs), "fallback должен логироваться"

    def test_passthrough_empty_collector_dict(self, monkeypatch):
        """collector: {} (присутствует, но пуст) — тоже fallback, не raise."""
        monkeypatch.setattr(collector_registry, "_factory", None)
        insp = collector_registry.build_collector({"collector": {}}, log_info=lambda m: None)
        assert isinstance(insp, PassThroughCollector)


class TestWithFactory:
    """С зарегистрированной фабрикой (реальный путь) — делегирует, не падает."""

    def test_delegates_to_factory(self, monkeypatch):
        captured = {}

        def fake_factory(app_cfg, **kw):
            captured["cfg"] = app_cfg
            return PassThroughCollector()

        monkeypatch.setattr(collector_registry, "_factory", fake_factory)
        collector_registry.build_collector({"collector": {"mode": "join"}})
        assert captured["cfg"] == {"collector": {"mode": "join"}}
