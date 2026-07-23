"""Тесты DeltaDispatcher — формат рассылки state.changed подписчикам.

Ключевая проверка: сообщение state.changed несёт queue_type="state" (Ф1.2/Ф6.1),
чтобы лечь в {subscriber}_state — очередь класса "state" с drop_oldest. Раньше
конверт шёл в never-drop {subscriber}_system, и burst state.set топил почту команд
подписчика (gui переставал отвечать вовсе — см. plans/truth-holes-closure.md Ф1).
"""

from __future__ import annotations

from ..core.delta import MISSING, Delta
from ..core.subscription_manager import SubscriptionManager
from ..manager.delta_dispatcher import DeltaDispatcher
import pytest
from ._deterministic_delivery import apply_deterministic_delivery


@pytest.fixture(autouse=True)
def _deterministic_state_delivery(monkeypatch):
    """Ф6.1: коалесцирование ON по дефолту — flush детерминированный, без тика.

    Тесты этого модуля проверяют ЧТО доставлено, а не КОГДА; расписание доставки —
    предмет ``test_delta_coalescing.py``. Подробности — в ``_deterministic_delivery``.
    """
    apply_deterministic_delivery(monkeypatch)


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


def test_state_changed_carries_state_queue_type() -> None:
    """state.changed → queue_type='state' (доставка в {sub}_state, drop_oldest)."""
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
    assert msg["queue_type"] == "state"
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
    assert router.sent[0]["queue_type"] == "state"


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


def test_envelope_carries_first_revision_min_of_batch() -> None:
    """Ф4.9-фикс (HIGH-1): data.first_revision == min(revision дельт пакета).

    Нужен StateProxy, чтобы отличить пакет из merge() на N≥2 листьев
    (revisions идут ПОДРЯД внутри ОДНОГО конверта, first_revision == last+1 —
    не разрыв) от реально пропущенного пакета (first_revision > last+1).
    """
    disp, router, subs = _make_dispatcher()
    subs.subscribe("processes.**", "gui")

    deltas = [
        Delta(path="processes.a", old_value=MISSING, new_value=1, source="s", revision=3),
        Delta(path="processes.b", old_value=MISSING, new_value=2, source="s", revision=7),
        Delta(path="processes.c", old_value=MISSING, new_value=3, source="s", revision=5),
    ]
    disp.dispatch(deltas)

    assert len(router.sent) == 1
    assert router.sent[0]["data"]["first_revision"] == 3
    assert router.sent[0]["data"]["revision"] == 7


def test_envelope_first_revision_equals_revision_for_single_delta() -> None:
    """Одна дельта в пакете — first_revision == revision (тривиальный диапазон)."""
    disp, router, subs = _make_dispatcher()
    subs.subscribe("processes.**", "gui")

    delta = Delta(path="processes.cam.state.status", old_value=MISSING, new_value="running", source="s", revision=5)
    disp.dispatch_single(delta)

    assert router.sent[0]["data"]["first_revision"] == 5
    assert router.sent[0]["data"]["revision"] == 5


def test_multi_leaf_merge_envelope_first_revision_is_contiguous_with_previous() -> None:
    """Ф4.9-фикс (HIGH-1) сквозной сценарий: merge на 2 листа даёт revisions [N+1, N+2]
    ОДНИМ конвертом — first_revision=N+1 стыкуется с предыдущим envelope (revision=N),
    подтверждая, что это НЕ разрыв (в отличие от старой проверки только по max)."""
    disp, router, subs = _make_dispatcher()
    subs.subscribe("cameras.0.**", "gui")

    # Первый пакет: одна дельта, revision=1 (имитирует предыдущее состояние клиента).
    disp.dispatch_single(
        Delta(path="cameras.0.state.status", old_value=MISSING, new_value="idle", source="s", revision=1)
    )

    # Второй пакет: merge на 2 листа → revisions 2 и 3 в ОДНОМ конверте.
    merge_deltas = [
        Delta(path="cameras.0.config.fps", old_value=MISSING, new_value=30, source="s", revision=2),
        Delta(path="cameras.0.config.type", old_value=MISSING, new_value="usb", source="s", revision=3),
    ]
    disp.dispatch(merge_deltas)

    assert len(router.sent) == 2
    first_envelope, second_envelope = router.sent[0]["data"], router.sent[1]["data"]
    assert first_envelope["revision"] == 1
    # first_revision второго пакета (2) == revision первого (1) + 1 — непрерывно.
    assert second_envelope["first_revision"] == first_envelope["revision"] + 1
    assert second_envelope["revision"] == 3
