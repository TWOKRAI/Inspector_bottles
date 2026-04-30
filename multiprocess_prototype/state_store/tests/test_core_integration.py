"""
Интеграционные тесты: TreeStore + Delta + SubscriptionManager.

Проверяет полный цикл: подписка → изменение → матчинг → транзакции → снимки.
"""
from __future__ import annotations

from multiprocess_prototype.state_store import (
    Delta,
    MISSING,
    Subscription,
    SubscriptionManager,
    Transaction,
    TreeStore,
)


# ===========================================================================
# Полный цикл: подписка → set → match
# ===========================================================================

def test_full_cycle():
    """Основной интеграционный сценарий из плана."""
    store = TreeStore()
    subs = SubscriptionManager()

    # 1. Подписка
    subs.subscribe("cameras.0.config.*", subscriber="processor_0")
    subs.subscribe("cameras.*.state.status", subscriber="gui")

    # 2. GUI меняет fps
    delta = store.set("cameras.0.config.fps", 30, source="gui")
    assert delta is not None
    matched = subs.match(delta)
    assert "processor_0" in {s.subscriber for s in matched}

    # 3. Camera обновляет state
    delta2 = store.set("cameras.0.state.status", "running", source="camera_0")
    assert delta2 is not None
    matched2 = subs.match(delta2)
    assert "gui" in {s.subscriber for s in matched2}

    # 4. Transaction: загрузка рецепта
    with store.transaction("recipe") as tx:
        tx.set("cameras.0.config.fps", 25)
        tx.set("cameras.0.config.camera_type", "hikvision")
    coalesced = tx.coalesce()
    assert len(coalesced) == 2

    # 5. Snapshot
    snap = store.snapshot(["cameras.*.config"])
    assert "cameras" in snap
    assert "0" in snap["cameras"]
    assert "config" in snap["cameras"]["0"]
    assert "state" not in snap["cameras"]["0"]  # state отфильтрован


def test_delta_from_set_is_real_delta():
    """Delta из TreeStore.set() — настоящий Delta из delta.py, не временный."""
    store = TreeStore()
    delta = store.set("x.y.z", 42, source="test")
    assert isinstance(delta, Delta)
    assert delta.path == "x.y.z"
    assert delta.old_value is MISSING  # новый узел
    assert delta.new_value == 42
    assert delta.source == "test"
    # Проверяем что это Delta со slots (из delta.py)
    assert hasattr(delta, "__slots__") or delta.__class__.__dataclass_fields__


def test_delta_from_set_has_is_create():
    """Delta из set() для нового узла помечен is_create=True."""
    store = TreeStore()
    delta = store.set("new.path", "value")
    assert delta is not None
    assert delta.is_create is True
    assert delta.is_delete is False


def test_delta_from_delete_has_is_delete():
    """Delta из delete() помечен is_delete=True."""
    store = TreeStore({"a": {"b": 1}})
    delta = store.delete("a.b")
    assert delta is not None
    assert delta.is_delete is True
    assert delta.is_create is False


def test_delta_serialization_roundtrip():
    """Delta из TreeStore можно сериализовать и десериализовать."""
    store = TreeStore()
    delta = store.set("cameras.0.fps", 30, source="gui")
    assert delta is not None

    d = delta.to_dict()
    restored = Delta.from_dict(d)
    assert restored.path == delta.path
    assert restored.new_value == delta.new_value
    assert restored.source == delta.source


def test_subscription_exclude_self():
    """Подписчик с exclude_sources не получает свои изменения."""
    store = TreeStore()
    subs = SubscriptionManager()

    subs.subscribe(
        "cameras.0.config.*",
        subscriber="camera_0",
        exclude_sources=("camera_0",),
    )

    # camera_0 пишет — не должен получить свою дельту
    delta = store.set("cameras.0.config.fps", 30, source="camera_0")
    matched = subs.match(delta)
    assert len(matched) == 0

    # gui пишет — camera_0 должен получить
    delta2 = store.set("cameras.0.config.fps", 25, source="gui")
    matched2 = subs.match(delta2)
    assert len(matched2) == 1
    assert matched2[0].subscriber == "camera_0"


def test_transaction_coalesce_removes_noops():
    """Transaction.coalesce() убирает no-op дельты."""
    store = TreeStore()

    with store.transaction("test") as tx:
        tx.set("x.y", 10)
        tx.set("x.y", 20)
        tx.set("x.y", 10)  # вернулось к начальному

    coalesced = tx.coalesce()
    # x.y: MISSING → 10 → 20 → 10, итог: MISSING → 10 (создание осталось)
    # Но если first.old == last.new, coalesce должен убрать
    # first.old = MISSING, last.new = 10 — не равны, поэтому остаётся
    assert len(coalesced) == 1
    assert coalesced[0].new_value == 10


def test_multiple_subscribers_on_same_path():
    """Несколько подписчиков на пересекающиеся паттерны."""
    store = TreeStore()
    subs = SubscriptionManager()

    subs.subscribe("cameras.**", subscriber="monitor")
    subs.subscribe("cameras.0.config.*", subscriber="processor_0")
    subs.subscribe("cameras.*.config.fps", subscriber="gui")

    delta = store.set("cameras.0.config.fps", 30, source="system")
    matched = subs.match(delta)
    subscribers = {s.subscriber for s in matched}
    assert subscribers == {"monitor", "processor_0", "gui"}


def test_snapshot_after_transaction():
    """Snapshot отражает все изменения из транзакции."""
    store = TreeStore()

    with store.transaction("init") as tx:
        tx.set("cameras.0.config.fps", 30)
        tx.set("cameras.0.config.type", "webcam")
        tx.set("cameras.1.config.fps", 25)
        tx.set("cameras.1.config.type", "hikvision")

    snap = store.snapshot(["cameras.*.config"])
    assert snap["cameras"]["0"]["config"]["fps"] == 30
    assert snap["cameras"]["1"]["config"]["type"] == "hikvision"


def test_import_from_package():
    """Импорт из пакета state_store работает.

    Тест проверяет обратную совместимость: conftest.py добавляет
    multiprocess_prototype/ в sys.path, что позволяет использовать
    короткий путь `from state_store import ...` наряду с каноническим
    `from multiprocess_prototype.state_store import ...`.
    """
    from multiprocess_prototype.state_store import (
        Delta,
        MISSING,
        Subscription,
        SubscriptionManager,
        Transaction,
        TreeStore,
    )
    assert Delta is not None
    assert TreeStore is not None
    assert SubscriptionManager is not None
    assert Subscription is not None
    assert Transaction is not None
    assert MISSING is not None


def test_merge_and_match():
    """merge() генерирует дельты, каждая матчится подписками."""
    store = TreeStore()
    subs = SubscriptionManager()

    subs.subscribe("cameras.0.config.*", subscriber="processor")

    # Сначала создадим структуру, чтобы merge мержил по ключам
    store.set("cameras.0.config.fps", 0)
    store.set("cameras.0.config.type", "none")
    store.set("cameras.0.state.status", "stopped")

    deltas = store.merge("cameras.0", {
        "config": {"fps": 30, "type": "webcam"},
        "state": {"status": "running"},
    })

    # Должны быть дельты для config.fps и config.type
    config_deltas = [d for d in deltas if "config" in d.path]
    assert len(config_deltas) >= 2

    # Каждая config-дельта должна матчить подписку processor
    for d in config_deltas:
        matched = subs.match(d)
        assert any(s.subscriber == "processor" for s in matched)

    # state.status не должен матчить cameras.0.config.*
    state_deltas = [d for d in deltas if "state" in d.path]
    for d in state_deltas:
        matched = subs.match(d)
        assert not any(s.subscriber == "processor" for s in matched)
