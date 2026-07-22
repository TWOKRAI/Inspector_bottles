"""Тесты tick-коалесцирования DeltaDispatcher (FW_STATE_COALESCE, Task 1.1).

Матрица:
  - OFF: путь бит-в-бит — N мутаций → N конвертов, поток flusher'а не создаётся.
  - ON: N мутаций внутри тика → ровно 1 конверт per-subscriber (first_revision=min,
    revision=max, монотонный порядок дельт); cap-flush при burst; shutdown-flush
    доставляет буфер и останавливает поток; сквозной сценарий с реальным StateProxy
    (непрерывность revision → resync НЕ запускается).

Флаг разрешается в ctor DeltaDispatcher (ctor > env > default), поэтому большинство
тестов задают режим явным аргументом ``coalesce=`` и дёргают ``_flush_once()``
детерминированно, НЕ ожидая реального таймера.
"""

from __future__ import annotations

from ..core.delta import MISSING, Delta
from ..core.subscription_manager import SubscriptionManager
from ..manager.delta_dispatcher import DeltaDispatcher
from ..manager.state_store_manager import StateStoreManager
from ..proxy.state_proxy import StateProxy


class _CapturingRouter:
    """Мини-роутер: захватывает send_async-сообщения (как в test_delta_dispatcher)."""

    def __init__(self) -> None:
        self.sent: list = []

    def send_async(self, msg, priority: str = "normal") -> None:
        self.sent.append(msg)


def _make(coalesce: bool | None, **kw) -> tuple[DeltaDispatcher, _CapturingRouter, SubscriptionManager]:
    subs = SubscriptionManager()
    router = _CapturingRouter()
    disp = DeltaDispatcher(subs, router=router, sender_name="StateStore", coalesce=coalesce, **kw)
    return disp, router, subs


def _mk_delta(path: str, value, revision: int) -> Delta:
    return Delta(path=path, old_value=MISSING, new_value=value, source="s", revision=revision)


# ---------------------------------------------------------------------------
# OFF — путь бит-в-бит
# ---------------------------------------------------------------------------


def test_off_is_bit_for_bit_one_envelope_per_mutation() -> None:
    """OFF: N set-мутаций → N конвертов, немедленно, без буфера."""
    disp, router, subs = _make(coalesce=False)
    subs.subscribe("processes.**", "gui")

    for i in range(5):
        disp.dispatch_single(_mk_delta("processes.cam.n", i, revision=i + 1))

    assert len(router.sent) == 5
    # Каждый конверт несёт ровно одну дельту, first_revision == revision.
    for i, msg in enumerate(router.sent):
        assert msg["command"] == "state.changed"
        assert msg["queue_type"] == "system"
        assert msg["targets"] == ["gui"]
        assert len(msg["data"]["deltas"]) == 1
        assert msg["data"]["first_revision"] == i + 1
        assert msg["data"]["revision"] == i + 1


def test_off_start_flusher_creates_no_thread() -> None:
    """OFF: start_flusher() не создаёт поток (поток не существует вовсе)."""
    disp, _router, _subs = _make(coalesce=False)
    disp.start_flusher()
    assert disp.coalescing_enabled is False
    assert disp._flusher is None


def test_off_buffer_stays_empty() -> None:
    """OFF: буфер не используется, dispatch не оставляет в нём ничего."""
    disp, _router, subs = _make(coalesce=False)
    subs.subscribe("processes.**", "gui")
    disp.dispatch_single(_mk_delta("processes.cam.n", 1, revision=1))
    assert disp._buffer == {}


# ---------------------------------------------------------------------------
# ON — буферизация до тика
# ---------------------------------------------------------------------------


def test_on_buffers_until_flush_one_envelope() -> None:
    """ON: несколько мутаций → в буфере, router молчит; _flush_once → 1 конверт."""
    disp, router, subs = _make(coalesce=True)
    subs.subscribe("processes.**", "gui")

    for i in range(4):
        disp.dispatch_single(_mk_delta("processes.cam.n", i, revision=i + 1))

    # До flush — ни одного отправленного сообщения.
    assert router.sent == []

    sent_count = disp._flush_once()
    assert sent_count == 1
    assert len(router.sent) == 1

    data = router.sent[0]["data"]
    assert len(data["deltas"]) == 4
    assert data["first_revision"] == 1  # min
    assert data["revision"] == 4  # max
    # Порядок дельт сохранён (монотонная revision).
    revs = [d["revision"] for d in data["deltas"]]
    assert revs == [1, 2, 3, 4]


def test_on_flush_is_empty_when_nothing_buffered() -> None:
    """ON: пустой тик → 0 конвертов, router молчит."""
    disp, router, _subs = _make(coalesce=True)
    assert disp._flush_once() == 0
    assert router.sent == []


def test_on_per_subscriber_isolation() -> None:
    """ON: два подписчика на разные паттерны → по одному конверту каждому на тике."""
    disp, router, subs = _make(coalesce=True)
    subs.subscribe("cameras.**", "gui")
    subs.subscribe("robots.**", "panel")

    disp.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=1))
    disp.dispatch_single(_mk_delta("robots.arm.x", 5, revision=2))
    disp.dispatch_single(_mk_delta("cameras.0.fps", 31, revision=3))

    assert router.sent == []
    disp._flush_once()

    by_target = {msg["targets"][0]: msg for msg in router.sent}
    assert set(by_target) == {"gui", "panel"}
    assert len(by_target["gui"]["data"]["deltas"]) == 2
    assert by_target["gui"]["data"]["first_revision"] == 1
    assert by_target["gui"]["data"]["revision"] == 3
    assert len(by_target["panel"]["data"]["deltas"]) == 1


def test_on_match_at_mutation_not_at_flush() -> None:
    """ON: подписчик, появившийся ПОСЛЕ мутации, не получает буферизованные дельты.

    Ключевой инвариант: матчинг подписок происходит в момент dispatch, а не при
    flush. Дельта замучена ДО подписки 'late' → в конверт 'late' не попадает.
    """
    disp, router, subs = _make(coalesce=True)
    subs.subscribe("cameras.**", "gui")

    disp.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=1))

    # Новый подписчик появляется МЕЖДУ мутацией и flush.
    subs.subscribe("cameras.**", "late")

    disp._flush_once()

    targets = {msg["targets"][0] for msg in router.sent}
    assert targets == {"gui"}  # 'late' не получил чужую буферизованную дельту


def test_on_no_keep_last_dedup_revision_contiguous() -> None:
    """ON: дедуп keep-last-per-path ЗАПРЕЩЁН — все мутации одного пути сохранены.

    Три записи в ОДИН путь → три дельты в конверте (непрерывный диапазон revision),
    а не одна «последняя». Иначе рвётся непрерывность revision у клиента.
    """
    disp, router, subs = _make(coalesce=True)
    subs.subscribe("cameras.**", "gui")

    disp.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=1))
    disp.dispatch_single(_mk_delta("cameras.0.fps", 31, revision=2))
    disp.dispatch_single(_mk_delta("cameras.0.fps", 32, revision=3))

    disp._flush_once()
    data = router.sent[0]["data"]
    revs = [d["revision"] for d in data["deltas"]]
    assert revs == [1, 2, 3]  # ни одна не поглощена
    assert data["first_revision"] == 1
    assert data["revision"] == 3


# ---------------------------------------------------------------------------
# ON — cap-flush (защита от burst)
# ---------------------------------------------------------------------------


def test_on_cap_triggers_immediate_flush() -> None:
    """ON: буфер достиг cap → немедленный flush подписчика, не дожидаясь тика."""
    disp, router, subs = _make(coalesce=True, buffer_cap=200)
    subs.subscribe("cameras.**", "gui")

    # 199 дельт — ещё под порогом, ничего не ушло.
    for i in range(199):
        disp.dispatch_single(_mk_delta("cameras.0.n", i, revision=i + 1))
    assert router.sent == []

    # 200-я дельта достигает cap → немедленный flush.
    disp.dispatch_single(_mk_delta("cameras.0.n", 199, revision=200))
    assert len(router.sent) == 1
    assert len(router.sent[0]["data"]["deltas"]) == 200
    # Буфер подписчика очищен после cap-flush.
    assert "gui" not in disp._buffer


def test_on_cap_flush_only_over_cap_subscriber() -> None:
    """ON: cap-flush касается только переполненного подписчика, остальные ждут тика."""
    disp, router, subs = _make(coalesce=True, buffer_cap=10)
    subs.subscribe("cameras.**", "gui")
    subs.subscribe("robots.**", "panel")

    disp.dispatch_single(_mk_delta("robots.arm.x", 1, revision=1))  # panel: 1 дельта, ждёт
    for i in range(10):
        disp.dispatch_single(_mk_delta("cameras.0.n", i, revision=i + 2))  # gui достигает cap

    assert len(router.sent) == 1
    assert router.sent[0]["targets"] == ["gui"]
    # panel всё ещё в буфере — cap-flush его не тронул.
    assert "panel" in disp._buffer
    assert "gui" not in disp._buffer


# ---------------------------------------------------------------------------
# ON — lifecycle через StateStoreManager (start/shutdown-flush)
# ---------------------------------------------------------------------------


def test_shutdown_flushes_buffer_and_stops_thread(monkeypatch) -> None:
    """ON через менеджер: буфер в flusher'е + shutdown() → буфер доставлен, поток стоит."""
    monkeypatch.setenv("FW_STATE_COALESCE", "1")

    router = _CapturingRouter()
    mgr = StateStoreManager(router=router, auto_register_ipc=False)
    assert mgr.dispatcher.coalescing_enabled is True

    mgr.subscription_manager.subscribe("cameras.**", "gui")
    mgr.initialize()
    assert mgr.dispatcher._flusher is not None
    assert mgr.dispatcher._flusher.is_alive()

    # Мутация → в буфер, конверт ещё не ушёл (тик 120мс не наступил).
    mgr.store.set("cameras.0.fps", 30, source="test")
    mgr.dispatcher.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=mgr.store.revision))
    assert router.sent == []

    mgr.shutdown()

    # Финальный flush доставил буфер ровно одним конвертом.
    assert len(router.sent) == 1
    assert router.sent[0]["targets"] == ["gui"]
    # Поток остановлен и снят.
    assert mgr.dispatcher._flusher is None


def test_off_manager_lifecycle_no_thread(monkeypatch) -> None:
    """OFF через менеджер: initialize/shutdown не создают flusher, путь бит-в-бит."""
    monkeypatch.delenv("FW_STATE_COALESCE", raising=False)

    router = _CapturingRouter()
    mgr = StateStoreManager(router=router, auto_register_ipc=False)
    assert mgr.dispatcher.coalescing_enabled is False

    mgr.subscription_manager.subscribe("cameras.**", "gui")
    mgr.initialize()
    assert mgr.dispatcher._flusher is None

    mgr.dispatcher.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=1))
    assert len(router.sent) == 1  # немедленно, без буфера

    mgr.shutdown()
    assert mgr.dispatcher._flusher is None


# ---------------------------------------------------------------------------
# ON — сквозной с реальным StateProxy: непрерывность revision → resync НЕ запускается
# ---------------------------------------------------------------------------


def test_on_end_to_end_stateproxy_no_resync() -> None:
    """ON: коалесцированный конверт с непрерывным диапазоном revision → StateProxy
    применяет дельты и НЕ запускает resync (диапазон [first_revision..revision]
    стыкуется с предыдущим)."""
    disp, router, subs = _make(coalesce=True)
    subs.subscribe("cameras.0.**", "gui")

    proxy = StateProxy("gui", router=None)
    proxy.initialize()
    # Регистрируем pattern локально, чтобы _advance_revision_and_maybe_resync
    # имел непустой набор паттернов для (потенциального) resync.
    proxy._sub_patterns["local-sub"] = "cameras.0.**"

    resync_calls: list = []
    proxy._resync = lambda patterns: resync_calls.append(patterns)  # type: ignore[method-assign]

    # База клиента: одиночный конверт revision=1.
    disp.dispatch_single(_mk_delta("cameras.0.state.status", "idle", revision=1))
    disp._flush_once()
    proxy.on_state_changed(router.sent[-1])
    assert proxy._last_revision == 1

    # Коалесцированный конверт: три мутации revision 2,3,4 в ОДНОМ конверте.
    disp.dispatch_single(_mk_delta("cameras.0.config.fps", 30, revision=2))
    disp.dispatch_single(_mk_delta("cameras.0.config.gain", 5, revision=3))
    disp.dispatch_single(_mk_delta("cameras.0.config.fps", 31, revision=4))
    disp._flush_once()
    envelope = router.sent[-1]
    assert envelope["data"]["first_revision"] == 2
    assert envelope["data"]["revision"] == 4

    proxy.on_state_changed(envelope)

    # Непрерывность (2 == last+1) → resync НЕ запущен, кэш сошёлся.
    assert resync_calls == []
    assert proxy._last_revision == 4
    assert proxy.cache["cameras.0.config.fps"] == 31
    assert proxy.cache["cameras.0.config.gain"] == 5
