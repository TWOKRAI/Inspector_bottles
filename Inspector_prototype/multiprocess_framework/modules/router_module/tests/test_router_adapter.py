# -*- coding: utf-8 -*-
"""Tests for RouterAdapter."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from ..adapters.router_adapter import RouterAdapter
from ..interfaces import IMessageChannel


class TestRouterAdapter(unittest.TestCase):

    def test_setup_returns_true_with_manager(self):
        mgr = MagicMock()
        ad = RouterAdapter(mgr)
        self.assertTrue(ad.setup())
        self.assertTrue(ad.is_initialized())

    def test_setup_returns_false_without_manager(self):
        ad = RouterAdapter(None)
        self.assertFalse(ad.setup())

    def test_send_delegates_to_manager(self):
        mgr = MagicMock()
        mgr.send.return_value = {"status": "success"}
        ad = RouterAdapter(mgr)
        ad.setup()
        out = ad.send({"command": "x"})
        mgr.send.assert_called_once()
        self.assertEqual(out["status"], "success")

    def test_send_without_manager_returns_error(self):
        ad = RouterAdapter(None)
        out = ad.send({"command": "x"})
        self.assertEqual(out["status"], "error")

    def test_send_async_delegates_to_manager(self):
        mgr = MagicMock()
        ad = RouterAdapter(mgr)
        ad.setup()
        ad.send_async({"command": "a"}, priority="high")
        mgr.send_async.assert_called_once_with({"command": "a"}, priority="high")

    def test_send_to_channel_adds_sender_field(self):
        mgr = MagicMock()
        mgr.send.return_value = {"status": "success"}
        proc = SimpleNamespace(name="worker_a")
        ad = RouterAdapter(mgr, proc)
        ad.setup()
        ad.send_to_channel("target_in", {"command": "ping"})
        mgr.send.assert_called_once()
        payload = mgr.send.call_args[0][0]
        self.assertEqual(payload["channel"], "target_in")
        self.assertEqual(payload["sender"], "worker_a")

    def test_receive_delegates_to_manager(self):
        mgr = MagicMock()
        mgr.receive.return_value = [{"command": "c"}]
        ad = RouterAdapter(mgr)
        ad.setup()
        self.assertEqual(ad.receive(timeout=0.05), [{"command": "c"}])
        mgr.receive.assert_called_once_with(timeout=0.05, return_messages=True)

    def test_register_channel_delegates(self):
        ch = MagicMock(spec=IMessageChannel)
        mgr = MagicMock()
        mgr.register_channel.return_value = True
        ad = RouterAdapter(mgr)
        ad.setup()
        self.assertTrue(ad.register_channel(ch))
        mgr.register_channel.assert_called_once_with(ch)

    def test_add_message_handler_delegates(self):
        mgr = MagicMock()
        mgr.register_message_handler.return_value = True
        ad = RouterAdapter(mgr)
        ad.setup()
        fn = lambda m: None
        self.assertTrue(ad.add_message_handler("k", fn))
        mgr.register_message_handler.assert_called_once_with("k", fn)

    def test_get_stats_includes_manager_stats(self):
        mgr = MagicMock()
        mgr.get_stats.return_value = {"router": {"sent_ok": 3}}
        ad = RouterAdapter(mgr)
        ad.setup()
        stats = ad.get_stats()
        self.assertEqual(stats["adapter_name"], "RouterAdapter")
        self.assertIn("manager", stats)
        self.assertEqual(stats["manager"]["router"]["sent_ok"], 3)

    def test_start_stop_listening(self):
        mgr = MagicMock()
        mgr.start_listening.return_value = True
        mgr.stop_listening.return_value = True
        ad = RouterAdapter(mgr)
        ad.setup()
        self.assertTrue(ad.start_listening(poll_interval=0.02))
        mgr.start_listening.assert_called_once_with(poll_interval=0.02)
        self.assertTrue(ad.stop_listening())
        mgr.stop_listening.assert_called_once()


if __name__ == "__main__":
    unittest.main()
