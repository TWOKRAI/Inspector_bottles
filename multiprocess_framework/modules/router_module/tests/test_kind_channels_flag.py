# -*- coding: utf-8 -*-
"""
Тесты флага ``use_kind_channels`` (Ф7 G.2 шаг 2).

Дефолт OFF → резолв бит-в-бит прежний (kind-блок пропущен). ON → исходящее
резолвится в ``{target}_{kind}`` (resolve_channel_kind + channel_name), если
такие каналы зарегистрированы; иначе аддитивно падаем в прежний путь.
"""

from __future__ import annotations

import unittest
from queue import Queue

from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager


def _ch(name: str) -> QueueChannel:
    return QueueChannel(name, Queue())


class TestFlagDefaultOff(unittest.TestCase):
    def test_default_is_off(self):
        router = RouterManager(manager_name="off_default")
        self.assertFalse(router._use_kind_channels)

    def test_explicit_true_enables(self):
        router = RouterManager(manager_name="on_explicit", use_kind_channels=True)
        self.assertTrue(router._use_kind_channels)

    def test_env_override_enables(self):
        import os

        prev = os.environ.get("MULTIPROCESS_USE_KIND_CHANNELS")
        os.environ["MULTIPROCESS_USE_KIND_CHANNELS"] = "1"
        try:
            router = RouterManager(manager_name="on_env")
            self.assertTrue(router._use_kind_channels)
        finally:
            if prev is None:
                del os.environ["MULTIPROCESS_USE_KIND_CHANNELS"]
            else:
                os.environ["MULTIPROCESS_USE_KIND_CHANNELS"] = prev

    def test_explicit_false_beats_env(self):
        import os

        prev = os.environ.get("MULTIPROCESS_USE_KIND_CHANNELS")
        os.environ["MULTIPROCESS_USE_KIND_CHANNELS"] = "1"
        try:
            router = RouterManager(manager_name="off_explicit", use_kind_channels=False)
            self.assertFalse(router._use_kind_channels)
        finally:
            if prev is None:
                del os.environ["MULTIPROCESS_USE_KIND_CHANNELS"]
            else:
                os.environ["MULTIPROCESS_USE_KIND_CHANNELS"] = prev


class TestKindChannelResolutionOn(unittest.TestCase):
    """Флаг ON: {target}_{kind} выигрывает при наличии в реестре."""

    def setUp(self):
        self.router = RouterManager(manager_name="kind_on", use_kind_channels=True)
        for name in ("worker_a_data", "worker_a_system", "worker_a_state"):
            self.router.register_channel(_ch(name))
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_data_message_routes_to_data_kind_channel(self):
        chans = self.router._resolve_channels({"type": "data", "targets": ["worker_a"], "data": {}})
        self.assertEqual([c.name for c in chans], ["worker_a_data"])

    def test_command_routes_to_system_kind_channel(self):
        chans = self.router._resolve_channels({"type": "command", "command": "do.thing", "targets": ["worker_a"]})
        self.assertEqual([c.name for c in chans], ["worker_a_system"])

    def test_state_command_routes_to_state_kind_channel(self):
        chans = self.router._resolve_channels(
            {"type": "command", "command": "state.merge", "targets": ["worker_a"], "data": {}}
        )
        self.assertEqual([c.name for c in chans], ["worker_a_state"])

    def test_hierarchical_target_uses_process_prefix(self):
        chans = self.router._resolve_channels({"type": "data", "targets": ["worker_a.slot1"], "data": {}})
        self.assertEqual([c.name for c in chans], ["worker_a_data"])

    def test_fanout_multiple_targets(self):
        self.router.register_channel(_ch("worker_b_data"))
        chans = self.router._resolve_channels({"type": "data", "targets": ["worker_a", "worker_b"], "data": {}})
        self.assertEqual(sorted(c.name for c in chans), ["worker_a_data", "worker_b_data"])


class TestKindChannelFallthrough(unittest.TestCase):
    """Флаг ON, но kind-канала нет в реестре → падаем в прежний путь (dispatcher)."""

    def setUp(self):
        self.router = RouterManager(manager_name="kind_fallthrough", use_kind_channels=True)
        self.legacy = _ch("legacy_ch")
        self.router.register_channel(self.legacy)
        self.router.register_route("do.thing", "legacy_ch")
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_no_kind_channel_falls_back_to_route(self):
        # kind-канала worker_x_system нет → dispatcher-маршрут выигрывает
        chans = self.router._resolve_channels({"type": "command", "command": "do.thing", "targets": ["worker_x"]})
        self.assertEqual([c.name for c in chans], ["legacy_ch"])

    def test_no_targets_falls_back(self):
        chans = self.router._resolve_channels({"type": "command", "command": "do.thing"})
        self.assertEqual([c.name for c in chans], ["legacy_ch"])


if __name__ == "__main__":
    unittest.main()
