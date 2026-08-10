# -*- coding: utf-8 -*-
"""Тесты фабрики build_collector (C6 b) — выбор буфера по mode + self-register.

Parity-контракт: тот же выбор, что делал generic_process._build_inspector до переноса
(имя шва стало универсальным в D4: build_collector) —
дефолт/fanin → InspectorManager, join → JoinInspectorManager. Плюс проверка, что импорт
Plugins._shared.fanin регистрирует фабрику в framework-реестре (DI-шов generic-движка).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic import collector_registry

from Plugins._shared.fanin import build_collector
from Plugins._shared.fanin.inspector_manager import InspectorManager
from Plugins._shared.fanin.join_inspector_manager import JoinInspectorManager


class TestModeSelection:
    def test_default_is_fanin(self):
        insp = build_collector({})
        assert isinstance(insp, InspectorManager)

    def test_explicit_fanin(self):
        insp = build_collector({"collector": {"mode": "fanin"}})
        assert isinstance(insp, InspectorManager)

    def test_join_mode(self):
        insp = build_collector({"collector": {"mode": "join", "inputs": ["frame", "overlay"]}})
        assert isinstance(insp, JoinInspectorManager)

    def test_empty_collector_section_is_fanin(self):
        insp = build_collector({"collector": {}})
        assert isinstance(insp, InspectorManager)


class TestJoinParams:
    def test_join_honors_primary_and_timeout(self):
        insp = build_collector(
            {"collector": {"mode": "join", "inputs": ["frame", "mask"], "primary": "frame", "timeout_sec": 0.2}}
        )
        assert isinstance(insp, JoinInspectorManager)
        # primary всегда в required-наборе
        assert "frame" in insp._required
        assert "mask" in insp._required


class TestSelfRegister:
    def test_factory_registered_in_framework_registry(self):
        """Импорт Plugins._shared.fanin зарегистрировал фабрику → build_collector реестра
        возвращает доменный буфер, а не PassThroughCollector-fallback."""
        insp = collector_registry.build_collector({"collector": {"mode": "fanin"}})
        assert isinstance(insp, InspectorManager)

    def test_registry_join_via_framework(self):
        insp = collector_registry.build_collector({"collector": {"mode": "join"}})
        assert isinstance(insp, JoinInspectorManager)
