# -*- coding: utf-8 -*-
"""Тесты фабрики build_inspector (C6 b) — выбор буфера по mode + self-register.

Parity-контракт: тот же выбор, что делал generic_process._build_inspector до переноса —
дефолт/fanin → InspectorManager, join → JoinInspectorManager. Плюс проверка, что импорт
Plugins._shared.fanin регистрирует фабрику в framework-реестре (DI-шов generic-движка).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic import inspector_registry

from Plugins._shared.fanin import build_inspector
from Plugins._shared.fanin.inspector_manager import InspectorManager
from Plugins._shared.fanin.join_inspector_manager import JoinInspectorManager


class TestModeSelection:
    def test_default_is_fanin(self):
        insp = build_inspector({})
        assert isinstance(insp, InspectorManager)

    def test_explicit_fanin(self):
        insp = build_inspector({"inspector": {"mode": "fanin"}})
        assert isinstance(insp, InspectorManager)

    def test_join_mode(self):
        insp = build_inspector({"inspector": {"mode": "join", "inputs": ["frame", "overlay"]}})
        assert isinstance(insp, JoinInspectorManager)

    def test_empty_inspector_section_is_fanin(self):
        insp = build_inspector({"inspector": {}})
        assert isinstance(insp, InspectorManager)


class TestJoinParams:
    def test_join_honors_primary_and_timeout(self):
        insp = build_inspector(
            {"inspector": {"mode": "join", "inputs": ["frame", "mask"], "primary": "frame", "timeout_sec": 0.2}}
        )
        assert isinstance(insp, JoinInspectorManager)
        # primary всегда в required-наборе
        assert "frame" in insp._required
        assert "mask" in insp._required


class TestSelfRegister:
    def test_factory_registered_in_framework_registry(self):
        """Импорт Plugins._shared.fanin зарегистрировал фабрику → build_inspector реестра
        возвращает доменный буфер, а не PassThroughInspector-fallback."""
        insp = inspector_registry.build_inspector({"inspector": {"mode": "fanin"}})
        assert isinstance(insp, InspectorManager)

    def test_registry_join_via_framework(self):
        insp = inspector_registry.build_inspector({"inspector": {"mode": "join"}})
        assert isinstance(insp, JoinInspectorManager)
