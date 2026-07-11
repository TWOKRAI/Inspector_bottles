"""Тесты DeltaDispatcher — формат рассылки state.changed подписчикам.

Ключевая проверка (U1/1.0b): сообщение state.changed несёт queue_type="system",
чтобы лечь в {subscriber}_system и быть обработанным штатным message_processor.
"""

from __future__ import annotations

from ..core.delta import MISSING, Delta
from ..core.subscription_manager import SubscriptionManager
from ..manager.delta_dispatcher import DeltaDispatcher


class _CapturingRouter:
    """Мини-роутер: захватывает send_async-сообщения."""

    def __init__(self) -> None:
        self.sent: list = []

    def send_async(self, msg, priority: str = "normal") -> None:
        self.sent.append(msg)


def _make_dispatcher() -> tuple[DeltaDispatcher, _CapturingRouter, SubscriptionManager]:
    subs = SubscriptionManager()
    router = _CapturingRouter()
    disp = DeltaDispatcher(subs, router=router, sender_name="StateStore")
    return disp, router, subs


def test_state_changed_carries_system_queue_type() -> None:
    """state.changed → queue_type='system' (доставка в {sub}_system)."""
    disp, router, subs = _make_dispatcher()
    subs.subscribe("processes.**", "gui")

    delta = Delta(
        path="processes.cam.state.status",
        old_value=MISSING,
        new_value="running",
        source="ProcessMonitor",
    )
    disp.dispatch_single(delta)

    assert len(router.sent) == 1
    msg = router.sent[0]
    assert msg["queue_type"] == "system"
    assert msg["command"] == "state.changed"
    assert msg["targets"] == ["gui"]
    assert msg["data"]["deltas"][0]["path"] == "processes.cam.state.status"


def test_no_subscribers_no_send() -> None:
    """Нет подписчиков → ничего не отправляется."""
    disp, router, _subs = _make_dispatcher()
    delta = Delta(path="processes.cam.state.status", old_value=MISSING, new_value="x", source="pm")
    disp.dispatch_single(delta)
    assert router.sent == []


def test_worker_telemetry_path_matches_subscription() -> None:
    """processes.X.workers.Y.* доставляется подписчику processes.**."""
    disp, router, subs = _make_dispatcher()
    subs.subscribe("processes.**", "gui")

    delta = Delta(
        path="processes.cam0.workers.w1.effective_hz",
        old_value=MISSING,
        new_value=12.5,
        source="ProcessMonitor",
    )
    disp.dispatch_single(delta)

    assert len(router.sent) == 1
    assert router.sent[0]["targets"] == ["gui"]
    assert router.sent[0]["queue_type"] == "system"


# ---------------------------------------------------------------------------
# Тесты revision в envelope (Ф4.9a, ADR-SS-014)
# ---------------------------------------------------------------------------


def test_envelope_carries_delta_revision() -> None:
    """state.changed несёт data.revision == revision единственной дельты."""
    disp, router, subs = _make_dispatcher()
    subs.subscribe("processes.**", "gui")

    delta = Delta(
        path="processes.cam.state.status",
        old_value=MISSING,
        new_value="running",
        source="ProcessMonitor",
        revision=5,
    )
    disp.dispatch_single(delta)

    assert router.sent[0]["data"]["revision"] == 5


def test_envelope_revision_is_max_of_batch() -> None:
    """Пакет из нескольких дельт → data.revision == max(revision дельт пакета)."""
    disp, router, subs = _make_dispatcher()
    subs.subscribe("processes.**", "gui")

    deltas = [
        Delta(path="processes.a", old_value=MISSING, new_value=1, source="s", revision=3),
        Delta(path="processes.b", old_value=MISSING, new_value=2, source="s", revision=7),
        Delta(path="processes.c", old_value=MISSING, new_value=3, source="s", revision=5),
    ]
    disp.dispatch(deltas)

    assert len(router.sent) == 1
    assert router.sent[0]["data"]["revision"] == 7
