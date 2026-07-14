"""Тесты QoS-профилей (Ф7 G.4.a) + проводки QueueRegistry.remove_old_if_full.

QoS = единый источник never-drop/drop_oldest для 3 поверхностей переполнения. Здесь —
контракт профиля + очередь: system никогда не дропается, data дропается ГРОМКО
(счётчик data_evicted), откат по флагу бит-в-бит.
"""

import queue as _queue

import pytest

from ..qos import (
    BEST_EFFORT,
    DROP_NEVER,
    DROP_OLDEST,
    RELIABLE,
    QoSProfile,
    qos_for,
)
from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry


# --- Контракт профиля -------------------------------------------------------------


class TestQoSProfile:
    def test_system_never_drop(self):
        assert qos_for("system").never_drop is True
        assert qos_for("command").never_drop is True
        assert qos_for("system").reliability == RELIABLE

    def test_data_drop_oldest(self):
        p = qos_for("data")
        assert p.never_drop is False
        assert p.drop_policy == DROP_OLDEST
        assert p.reliability == BEST_EFFORT
        assert p.history_depth >= 1  # keep_last несколько кадров

    def test_state_coalesce(self):
        assert qos_for("state").history_depth == 1  # важен последний снимок

    def test_unknown_kind_defaults_to_data(self):
        """Неизвестный класс груза → data-политика (droppable), НЕ never-drop."""
        assert qos_for("totally-unknown").never_drop is False
        assert qos_for("totally-unknown").drop_policy == DROP_OLDEST

    def test_reliable_iff_never_invariant(self):
        """reliable ⟺ never — противоречивый профиль запрещён."""
        with pytest.raises(ValueError):
            QoSProfile(RELIABLE, 0, DROP_OLDEST, 0)  # reliable но droppable
        with pytest.raises(ValueError):
            QoSProfile(BEST_EFFORT, 0, DROP_NEVER, 0)  # never но best_effort

    def test_bad_values_rejected(self):
        with pytest.raises(ValueError):
            QoSProfile("bogus", 0, DROP_NEVER, 0)
        with pytest.raises(ValueError):
            QoSProfile(BEST_EFFORT, -1, DROP_OLDEST, 0)
        with pytest.raises(ValueError):
            QoSProfile(BEST_EFFORT, 4, "bogus", 0)
        with pytest.raises(ValueError):
            QoSProfile(BEST_EFFORT, 4, DROP_OLDEST, -5)

    def test_frozen(self):
        with pytest.raises(Exception):
            qos_for("data").history_depth = 99  # frozen dataclass


# --- Проводка в QueueRegistry.remove_old_if_full ----------------------------------


def _qr(qos_profiles: bool) -> QueueRegistry:
    reg = QueueRegistry(process_state_registry=ProcessStateRegistry(), qos_profiles=qos_profiles)
    reg.initialize()
    return reg


def _full_queue():
    """queue.Queue(maxsize=1) с одним элементом — full()=True, get_nowait() детерминирован."""
    q = _queue.Queue(maxsize=1)
    q.put("old")
    return q


@pytest.mark.parametrize("flag", [False, True])
class TestRemoveOldIfFull:
    def test_system_never_evicted(self, flag):
        """system-очередь: элемент НЕ вытесняется, счётчик system_evict_blocked растёт."""
        reg = _qr(flag)
        q = _full_queue()
        reg.remove_old_if_full(q, "system")
        assert q.qsize() == 1  # старый элемент цел
        assert q.get_nowait() == "old"
        assert reg._stats["system_evict_blocked"] == 1
        assert reg._stats["data_evicted"] == 0

    def test_data_evicted_loudly(self, flag):
        """data-очередь: старый элемент вытеснен, счётчик data_evicted растёт (не тихо)."""
        reg = _qr(flag)
        q = _full_queue()
        reg.remove_old_if_full(q, "data")
        assert q.qsize() == 0  # старый вытеснен, место освобождено
        assert reg._stats["data_evicted"] == 1
        assert reg._stats["system_evict_blocked"] == 0

    def test_not_full_is_noop(self, flag):
        reg = _qr(flag)
        q = _queue.Queue(maxsize=2)
        q.put("a")
        reg.remove_old_if_full(q, "data")
        assert q.qsize() == 1
        assert reg._stats["data_evicted"] == 0

    def test_none_queue_type_droppable(self, flag):
        """queue_type=None → droppable (прежнее поведение data-ветки)."""
        reg = _qr(flag)
        q = _full_queue()
        reg.remove_old_if_full(q, None)
        assert q.qsize() == 0
        assert reg._stats["data_evicted"] == 1


def test_flag_off_verdict_is_hardcoded_source():
    """Флаг OFF → вердикт never-drop из хардкода queue_type=='system' (бит-в-бит откат)."""
    reg = _qr(False)
    assert reg._is_never_drop("system") is True
    assert reg._is_never_drop("data") is False
    assert reg._is_never_drop(None) is False


def test_flag_on_verdict_from_profile():
    """Флаг ON → вердикт из QoS-профиля; для system/data совпадает с хардкодом."""
    reg = _qr(True)
    assert reg._is_never_drop("system") is True
    assert reg._is_never_drop("command") is True  # профиль знает command=never (хардкод — нет)
    assert reg._is_never_drop("data") is False
    assert reg._is_never_drop("state") is False
