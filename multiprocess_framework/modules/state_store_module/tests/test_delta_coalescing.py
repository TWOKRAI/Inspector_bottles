"""Тесты tick-коалесцирования DeltaDispatcher (Task 1.1 + Ф6.3).

Что проверяется: N мутаций внутри тика → ровно 1 конверт per-subscriber
(first_revision=min, revision=max, монотонный порядок дельт); cap-flush при burst;
shutdown-flush доставляет буфер и останавливает поток; сквозной сценарий с реальным
StateProxy (непрерывность revision → resync НЕ запускается).

Плечо OFF удалено вместе с флагом ``FW_STATE_COALESCE`` (Ф6.3, решение владельца —
вариант A): коалесцирование стало единственным путём, и тестировать снятую ветку
значило бы держать её живой. Тесты дёргают ``_flush_once()`` детерминированно,
НЕ ожидая реального таймера.
"""

from __future__ import annotations

import threading

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


def _make(**kw) -> tuple[DeltaDispatcher, _CapturingRouter, SubscriptionManager]:
    subs = SubscriptionManager()
    router = _CapturingRouter()
    disp = DeltaDispatcher(subs, router=router, sender_name="StateStore", **kw)
    return disp, router, subs


def _mk_delta(path: str, value, revision: int) -> Delta:
    return Delta(path=path, old_value=MISSING, new_value=value, source="s", revision=revision)


# ---------------------------------------------------------------------------
# Конверт: формат и адресация (единственный путь)
# ---------------------------------------------------------------------------


def test_envelope_format_and_queue_class() -> None:
    """Конверт state.changed адресован подписчику и едет очередью класса "state".

    Ф6.2 сняла выбор очереди, Ф6.3 — выбор режима доставки: обе плоскости стали
    единственным путём, поэтому формат проверяется один раз здесь.
    """
    disp, router, subs = _make()
    subs.subscribe("processes.**", "gui")

    disp.dispatch_single(_mk_delta("processes.cam.n", 1, revision=1))
    disp._flush_once()

    assert len(router.sent) == 1
    msg = router.sent[0]
    assert msg["command"] == "state.changed"
    assert msg["queue_type"] == "state"
    assert msg["targets"] == ["gui"]
    assert msg["data"]["first_revision"] == 1
    assert msg["data"]["revision"] == 1


# ---------------------------------------------------------------------------
# Буферизация до тика
# ---------------------------------------------------------------------------


def test_buffers_until_flush_one_envelope() -> None:
    """Несколько мутаций → в буфере, router молчит; _flush_once → 1 конверт."""
    disp, router, subs = _make()
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


def test_flush_is_empty_when_nothing_buffered() -> None:
    """Пустой тик → 0 конвертов, router молчит."""
    disp, router, _subs = _make()
    assert disp._flush_once() == 0
    assert router.sent == []


def test_per_subscriber_isolation() -> None:
    """Два подписчика на разные паттерны → по одному конверту каждому на тике."""
    disp, router, subs = _make()
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


def test_match_at_mutation_not_at_flush() -> None:
    """Подписчик, появившийся ПОСЛЕ мутации, не получает буферизованные дельты.

    Ключевой инвариант: матчинг подписок происходит в момент dispatch, а не при
    flush. Дельта замучена ДО подписки 'late' → в конверт 'late' не попадает.
    """
    disp, router, subs = _make()
    subs.subscribe("cameras.**", "gui")

    disp.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=1))

    # Новый подписчик появляется МЕЖДУ мутацией и flush.
    subs.subscribe("cameras.**", "late")

    disp._flush_once()

    targets = {msg["targets"][0] for msg in router.sent}
    assert targets == {"gui"}  # 'late' не получил чужую буферизованную дельту


def test_no_keep_last_dedup_revision_contiguous() -> None:
    """Дедуп keep-last-per-path ЗАПРЕЩЁН — все мутации одного пути сохранены.

    Три записи в ОДИН путь → три дельты в конверте (непрерывный диапазон revision),
    а не одна «последняя». Иначе рвётся непрерывность revision у клиента.
    """
    disp, router, subs = _make()
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
# cap-flush (защита от burst)
# ---------------------------------------------------------------------------


def test_cap_wakes_flusher_does_not_send_in_caller() -> None:
    """Cap НЕ шлёт в вызывающем (мутаторском) потоке — только будит flusher.

    Инвариант антигонки (ревью Fable): отправка cap-путём из потока-мутатора при
    ≥2 мутаторах переупорядочила бы конверты (pop-под-локом vs send-вне-лока) и
    приёмник бесшумно проглотил бы «устаревший» пакет. Здесь: при достижении cap
    _wake выставлен, буфер НЕ очищен, _send_state_changed из caller-потока НЕ звался.
    Реальная отправка идёт только через _flush_once (эмулирует поток flusher'а).
    """
    disp, router, subs = _make(buffer_cap=50)
    subs.subscribe("cameras.**", "gui")

    send_threads: list[int] = []
    orig_send = disp._send_state_changed

    def _spy(sub: str, deltas) -> None:
        send_threads.append(threading.get_ident())
        orig_send(sub, deltas)

    disp._send_state_changed = _spy  # type: ignore[method-assign]

    for i in range(50):  # достигаем cap ровно
        disp.dispatch_single(_mk_delta("cameras.0.n", i, revision=i + 1))

    # cap достигнут: flusher разбужен, но НИ ОДНОЙ отправки из caller-потока.
    assert disp._wake.is_set()
    assert send_threads == []
    assert len(disp._buffer["gui"]) == 50  # буфер цел, не выслан в мутаторе

    # Отправка происходит только в flush_once (поток flusher'а).
    sent = disp._flush_once()
    assert sent == 1
    assert len(send_threads) == 1
    assert send_threads[0] == threading.get_ident()  # тут это тот же поток теста
    assert router.sent[-1]["data"]["revision"] == 50
    assert "gui" not in disp._buffer


def test_cap_single_flush_preserves_order_no_gaps() -> None:
    """Серия [1..250] с cap=200 → один _flush_once после wake → строго
    возрастающие revision без дыр и обгона (тотальный порядок per-subscriber)."""
    disp, router, subs = _make(buffer_cap=200)
    subs.subscribe("cameras.**", "gui")

    for i in range(250):
        disp.dispatch_single(_mk_delta("cameras.0.n", i, revision=i + 1))

    # cap по пути достигнут (wake выставлен), но без запущенного flusher'а
    # в этом unit-тесте отправки не было — всё копится в буфере.
    assert router.sent == []
    assert disp._wake.is_set()
    assert len(disp._buffer["gui"]) == 250

    disp._flush_once()

    assert len(router.sent) == 1
    revs = [d["revision"] for d in router.sent[0]["data"]["deltas"]]
    assert revs == list(range(1, 251))  # возрастание без дыр, без переупорядочивания
    assert router.sent[0]["data"]["first_revision"] == 1
    assert router.sent[0]["data"]["revision"] == 250


def test_live_flusher_thread_cap_pressure_no_loss_no_reorder() -> None:
    """Со СБОРНЫМ потоком-flusher'ом под cap-давлением: единственный отправитель
    гарантирует, что все дельты доставлены ровно один раз, конверты строго
    возрастают по revision, потерь/обгона нет.

    Именно этот сценарий раньше ломала гонка: cap-flush в потоке-мутаторе
    конкурировал с потоком-flusher'ом → конверт [1..cap] обгонялся [cap+1] и
    бесшумно глотался приёмником. Один поток-отправитель эту гонку исключает.
    Финальные проверки — на СОБРАННОМ результате (не на таймингах): порядок
    батчей может варьироваться, но конкатенация обязана быть 1..N без дыр.
    """
    disp, router, subs = _make(buffer_cap=20, flush_interval_sec=0.005)
    subs.subscribe("cameras.**", "gui")
    disp.start_flusher()
    try:
        # Единственный поток-мутатор → revision назначаются и буферизуются строго
        # по возрастанию (кросс-тредовая гонка назначения revision — вне scope 1.1).
        for i in range(500):
            disp.dispatch_single(_mk_delta("cameras.0.n", i, revision=i + 1))
    finally:
        disp.stop_flusher()  # финальный дренаж остатка буфера

    # Все конверты пришли к gui.
    assert all(msg["targets"] == ["gui"] for msg in router.sent)
    # Конверты строго возрастают по revision в порядке отправки (нет обгона/стейла).
    env_revs = [msg["data"]["revision"] for msg in router.sent]
    assert env_revs == sorted(env_revs)
    assert len(set(env_revs)) == len(env_revs)
    # Конкатенация дельт всех конвертов = 1..500 ровно, без потерь и дублей.
    all_revs = [d["revision"] for msg in router.sent for d in msg["data"]["deltas"]]
    assert all_revs == list(range(1, 501))


# ---------------------------------------------------------------------------
# Lifecycle через StateStoreManager (start/shutdown-flush)
# ---------------------------------------------------------------------------


def test_shutdown_flushes_buffer_and_stops_thread() -> None:
    """Через менеджер: буфер в flusher'е + shutdown() → буфер доставлен, поток стоит."""
    router = _CapturingRouter()
    mgr = StateStoreManager(router=router, auto_register_ipc=False)

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


def test_manager_lifecycle_has_no_immediate_send_switch(monkeypatch) -> None:
    """Переключателя режима нет: env снятого флага ничего не меняет (Ф6.3).

    Страж от «отката по памяти»: `FW_STATE_COALESCE=0` в окружении когда-то
    возвращал немедленную отправку в потоке-мутаторе. Флаг удалён — env обязан
    быть проигнорирован, а не молча вернуть снятую ветку.
    """
    monkeypatch.setenv("FW_STATE_COALESCE", "0")

    router = _CapturingRouter()
    mgr = StateStoreManager(router=router, auto_register_ipc=False)

    mgr.subscription_manager.subscribe("cameras.**", "gui")
    mgr.initialize()
    assert mgr.dispatcher._flusher is not None  # поток есть вопреки env

    mgr.dispatcher.dispatch_single(_mk_delta("cameras.0.fps", 30, revision=1))
    assert router.sent == []  # буфер, а не немедленная отправка

    mgr.shutdown()
    assert mgr.dispatcher._flusher is None
    assert len(router.sent) == 1  # финальный дренаж доставил


# ---------------------------------------------------------------------------
# Сквозной с реальным StateProxy: непрерывность revision → resync НЕ запускается
# ---------------------------------------------------------------------------


def test_end_to_end_stateproxy_no_resync() -> None:
    """Коалесцированный конверт с непрерывным диапазоном revision → StateProxy
    применяет дельты и НЕ запускает resync (диапазон [first_revision..revision]
    стыкуется с предыдущим)."""
    disp, router, subs = _make()
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


# ---------------------------------------------------------------------------
# Initial-replay через единственного отправителя (ревью Fable, итерация 2)
# ---------------------------------------------------------------------------


def test_replay_not_sent_in_caller_thread() -> None:
    """Вызов enqueue_replay НЕ шлёт из вызывающего потока — только буферизует и будит
    flusher. Иначе конверт реплея конкурировал бы с буферизованным."""
    disp, router, _subs = _make()
    disp._wake.clear()

    disp.enqueue_replay("gui", [_mk_delta("cameras.0.status", "idle", revision=7)])

    assert router.sent == []  # отправки из caller-потока нет
    assert disp._wake.is_set()  # flusher разбужен
    assert disp._flush_once() == 1
    assert len(router.sent) == 1


def test_replay_appended_after_pending_one_envelope() -> None:
    """Реплей ложится ПОСЛЕ уже накопленных дельт подписчика — один конверт,
    first_revision = min(pending), непрерывность не рвётся, дропа нет."""
    disp, router, subs = _make()
    subs.subscribe("cameras.**", "gui")

    # Накопленные мутации 10..12 (ещё не отправлены).
    for rev in (10, 11, 12):
        disp.dispatch_single(_mk_delta("cameras.0.config.fps", rev, revision=rev))
    assert router.sent == []

    # Реплей снимка (revision снимка = 12, значения не старше pending).
    disp.enqueue_replay("gui", [_mk_delta("cameras.0.status", "idle", revision=12)])
    disp._flush_once()

    assert len(router.sent) == 1  # ровно ОДИН конверт
    data = router.sent[0]["data"]
    assert data["first_revision"] == 10  # min pending, а не revision реплея
    assert data["revision"] == 12
    # Порядок: сначала pending-дельты, реплей последним (снимок не откатывает pending).
    paths = [d["path"] for d in data["deltas"]]
    assert paths == [
        "cameras.0.config.fps",
        "cameras.0.config.fps",
        "cameras.0.config.fps",
        "cameras.0.status",
    ]


def test_stuck_flusher_skips_final_flush() -> None:
    """Зависший flusher → финальный дренаж ПРОПУСКАЕТСЯ (единственный отправитель).

    Предмерж-ревью Ф6: при join-таймауте старый код всё равно звал ``_flush_once`` из
    вызывающего потока, пока поток-flusher ещё жив, — два конкурентных отправителя
    переупорядочили бы конверты, а приёмник глушит «устаревший» пакет целиком.
    Инвариант порядка дороже хвоста буфера при аварийном shutdown.
    """
    disp, router, subs = _make()
    subs.subscribe("processes.**", "gui")

    class _ZombieThread:
        """Двойник потока, который не завершился за timeout."""

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return True

    disp._flusher = _ZombieThread()
    disp.dispatch_single(_mk_delta("processes.cam.n", 1, revision=1))
    disp.stop_flusher(timeout=0.01)

    assert router.sent == []  # ничего не отправлено вторым отправителем
    assert disp._flusher is None


def test_finished_flusher_does_final_flush() -> None:
    """Плечо пары: поток честно завершился → буфер дренируется, как и обещано."""
    disp, router, subs = _make(flush_interval_sec=5.0)
    subs.subscribe("processes.**", "gui")
    disp.start_flusher()
    disp.dispatch_single(_mk_delta("processes.cam.n", 1, revision=1))
    disp.stop_flusher(timeout=2.0)

    assert len(router.sent) == 1
    assert disp._flusher is None
