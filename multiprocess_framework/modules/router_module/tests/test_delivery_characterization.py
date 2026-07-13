# -*- coding: utf-8 -*-
"""
Характеризационные тесты доставки — GATE фазы Ф7 G.2 (vision §5.8).

«Слепки» ТЕКУЩЕГО поведения доставки на дефолте ``channel="queue"``, общие для
осей КАНАЛОВ и КОНВЕРТА команд. Назначение — зафиксировать бит-в-бит поведение
ДО правки резолва (kind-каналы за флагом, G.2 шаг 2) и до унификации конверта
(G.2 шаг 3) / снятия shape-sniffing ``state.merge`` (G.2 шаг 4).

Разделение ответственности ассертов:
  • ИНВАРИАНТ (не меняется ни на одном шаге G.2): выбор канала/очереди на дефолте,
    порядок доставки, семантика ``state.merge`` (что смёржилось и куда).
  • CHANGE-SURFACE (обновляется на шаге 3): точная ФОРМА двух исторических путей
    конверта команд (``MessageAdapter``→``args`` vs ``command_envelopes``→``data``).
    Здесь они зафиксированы «как есть сейчас»; после шага 3 (единый билдер) эти
    ассерты будут приведены к унифицированной форме — расхождение путей исчезнет.

Флаг ``use_kind_channels`` по умолчанию OFF: все ассерты этого файла обязаны быть
зелёными на нетронутом коде И оставаться зелёными при флаге OFF после шага 2.
"""

from __future__ import annotations

import unittest
from queue import Queue

from multiprocess_framework.modules.message_module import (
    MessageAdapter,
    build_command_message,
    build_system_command_message,
)
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
    StateStoreManager,
)

from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager


def _make_channel(name: str) -> tuple:
    q: Queue = Queue()
    return QueueChannel(name, q), q


class _FakeQueueRegistry:
    """Мини queue_registry: пишет (target, qtype, msg) в список sent."""

    def __init__(self) -> None:
        self.sent: list = []

    def send_to_queue(self, target, qtype, msg) -> bool:
        self.sent.append((target, qtype, msg))
        return True


# ===========================================================================
# ИНВАРИАНТ: выбор канала на дефолте "queue"
# ===========================================================================


class TestDefaultQueueChannelResolution(unittest.TestCase):
    """``channel="queue"`` трактуется как «канал не задан» → резолв идёт через
    зарегистрированный маршрут / dispatcher / targets, а не как реальный канал."""

    def setUp(self):
        self.router = RouterManager(manager_name="char_router")
        self.ch, self.q = _make_channel("char_ch")
        self.router.register_channel(self.ch)
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_queue_literal_is_not_a_real_channel(self):
        """Явный channel="queue" НЕ ищется как канал — проваливается в маршрут."""
        self.router.register_route("do_x", "char_ch")
        result = self.router.send({"command": "do_x", "channel": "queue", "data": {}})
        self.assertEqual(result["status"], "success")
        self.assertFalse(self.q.empty())

    def test_queue_literal_without_route_is_error_not_silent(self):
        """Нет маршрута и channel="queue" → ошибка (нет тихого drop)."""
        result = self.router.send({"command": "no_route", "channel": "queue", "data": {}})
        self.assertEqual(result["status"], "error")

    def test_registered_route_resolves_to_channel(self):
        self.router.register_route("routed_cmd", "char_ch")
        chans = self.router._resolve_channels({"command": "routed_cmd", "data": {}})
        self.assertEqual([c.name for c in chans], ["char_ch"])


class TestDeliveryOrdering(unittest.TestCase):
    """FIFO-порядок доставки в канал при синхронной отправке."""

    def setUp(self):
        self.router = RouterManager(manager_name="order_router")
        self.ch, self.q = _make_channel("order_ch")
        self.router.register_channel(self.ch)
        self.router.register_route("seq", "order_ch")
        self.router.initialize()

    def tearDown(self):
        self.router.shutdown()

    def test_sync_send_preserves_order(self):
        for i in range(10):
            self.router.send({"command": "seq", "data": {"n": i}})
        received = []
        while not self.q.empty():
            received.append(self.q.get_nowait()["data"]["n"])
        self.assertEqual(received, list(range(10)))


class TestDefaultQueueTypeMapping(unittest.TestCase):
    """ИНВАРИАНТ: target-aware fallback (_do_send) выбирает очередь по грузу.

    Текущее поведение (пин): command → system-очередь, НЕ-command (data/event) →
    data-очередь. Именно этот маппинг проводит kind-каналы (шаг 2), флаг OFF его
    не меняет."""

    def test_command_defaults_to_system_queue(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="qt_cmd", queue_registry=qr)
        router.send({"type": "command", "command": "do.thing", "targets": ["worker_a"]})
        self.assertEqual(qr.sent[0][1], "system")

    def test_data_defaults_to_data_queue(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="qt_data", queue_registry=qr)
        router.send({"type": "data", "targets": ["display_proc"], "data": {}})
        self.assertEqual(qr.sent[0][1], "data")

    def test_event_defaults_to_data_queue(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="qt_ev", queue_registry=qr)
        router.send({"type": "event", "command": "ev", "targets": ["p"]})
        self.assertEqual(qr.sent[0][1], "data")

    def test_explicit_queue_type_respected(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="qt_expl", queue_registry=qr)
        router.send({"type": "event", "command": "ev", "targets": ["p"], "queue_type": "system"})
        self.assertEqual(qr.sent[0][1], "system")


class TestFenceFieldsTravelOnDefault(unittest.TestCase):
    """ИНВАРИАНТ 4.2: fence-поля (sender_incarnation/epoch) едут в билете при
    target-aware доставке — резолв канала их не срезает."""

    def test_fence_fields_preserved_in_delivered_ticket(self):
        qr = _FakeQueueRegistry()
        router = RouterManager(manager_name="fence_router", queue_registry=qr)
        router.send(
            {
                "type": "command",
                "command": "do.thing",
                "targets": ["worker_a"],
                "sender_incarnation": 7,
                "epoch": 3,
            }
        )
        self.assertEqual(len(qr.sent), 1)
        _target, _qtype, ticket = qr.sent[0]
        self.assertEqual(ticket.get("sender_incarnation"), 7)
        self.assertEqual(ticket.get("epoch"), 3)


# ===========================================================================
# CHANGE-SURFACE: форма двух исторических путей конверта команд (шаг 3 обновит)
# ===========================================================================


class TestCommandEnvelopeFormatBefore(unittest.TestCase):
    """Слепок ДВУХ исторических форм конверта команд (до унификации, шаг 3).

    Путь A — ``command_envelopes.build_command_message``: payload под ключом
    ``data`` (канонический). Путь B — ``MessageAdapter.command``: payload под
    ключом ``args``. Расхождение этих двух форм — то, что снимает шаг 3."""

    def test_envelopes_builder_puts_payload_under_data(self):
        msg = build_command_message("camera_0", "set_fps", {"fps": 30}, sender="gui")
        self.assertEqual(msg["type"], "command")
        self.assertEqual(msg["command"], "set_fps")
        self.assertEqual(msg["data_type"], "set_fps")
        self.assertEqual(msg["sender"], "gui")
        self.assertEqual(msg["targets"], ["camera_0"])
        self.assertEqual(msg["data"], {"fps": 30})
        # исторически конверт-путь НЕ несёт отдельного args
        self.assertNotIn("args", msg)

    def test_message_adapter_puts_payload_under_args(self):
        adapter = MessageAdapter(sender="gui")
        msg = adapter.command(targets="camera_0", command="set_fps", args={"fps": 30}).to_dict()
        self.assertEqual(msg["type"], "command")
        self.assertEqual(msg["command"], "set_fps")
        # исторически MessageAdapter кладёт payload в args (расхождение с путём A)
        self.assertEqual(msg["args"], {"fps": 30})

    def test_system_command_wraps_under_data(self):
        inner = {"cmd": "process.stop", "process_name": "cam0"}
        msg = build_system_command_message(inner, sender="gui")
        self.assertEqual(msg["command"], "process.command")
        self.assertEqual(msg["targets"], ["ProcessManager"])
        self.assertEqual(msg["data"], inner)


# ===========================================================================
# ИНВАРИАНТ: семантика state.merge (что смёржилось и куда)
# ===========================================================================


class TestStateMergeBehaviorBefore(unittest.TestCase):
    """Слепок ПОВЕДЕНИЯ state.merge на обеих входных формах.

    Форма A (full message, router expects_full_message=True): конверт вложен в
    ``msg["data"]``. Форма B (уже развёрнутый data): конверт = сам ``msg``.
    Плюс кромка: payload сам несёт ключи ``path``/``source`` (device-config),
    прежний фолбэк на этом ломался. Что мёржится — инвариант шага 4."""

    def test_merge_form_a_full_message(self):
        mgr = StateStoreManager()
        result = mgr.handle_state_merge(
            {
                "command": "state.merge",
                "data": {"path": "cameras.0", "data": {"fps": 30, "type": "webcam"}, "source": "gui"},
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["path"], "cameras.0")
        self.assertEqual(mgr.store.get("cameras.0.fps"), 30)

    def test_merge_form_b_unwrapped_envelope(self):
        mgr = StateStoreManager()
        result = mgr.handle_state_merge({"path": "cameras.1", "data": {"fps": 25, "type": "hik"}, "source": "gui"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["path"], "cameras.1")
        self.assertEqual(mgr.store.get("cameras.1.fps"), 25)

    def test_merge_payload_carrying_source_key(self):
        """Payload сам содержит ключ 'source' (camera actual) — не должен теряться."""
        mgr = StateStoreManager()
        payload = {"source": "camera://0", "fps": 30}
        result = mgr.handle_state_merge({"path": "processes.cam0.state.cam.actual", "data": payload, "source": "cam0"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(mgr.store.get("processes.cam0.state.cam.actual.source"), "camera://0")

    def test_merge_payload_carrying_path_key(self):
        """Payload сам содержит ключ 'path' (device-config) — не должен теряться."""
        mgr = StateStoreManager()
        payload = {"path": "/dev/video0", "fps": 30}
        result = mgr.handle_state_merge({"path": "processes.dev.state", "data": payload, "source": "dev"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(mgr.store.get("processes.dev.state.path"), "/dev/video0")

    def test_merge_missing_data_is_error(self):
        mgr = StateStoreManager()
        result = mgr.handle_state_merge({"command": "state.merge", "data": {"path": "x"}})
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
