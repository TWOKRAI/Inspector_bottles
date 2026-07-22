"""Очередь класса "state" (FW_STATE_QUEUE): drop_oldest, а не never-drop.

Task 1.2 (truth-holes-closure): state.changed уходит в ``{proc}_state`` вместо
never-drop system-очереди. Ключевой инвариант — переполнение state-очереди
роняет самый старый конверт (drop_oldest, счётчик ``data_evicted``), а НЕ
блокирует вытеснение как system (``system_evict_blocked``). Клиент восстановит
разрыв revision через resync. Проверяется на ОБОИХ путях ``FW_QOS_PROFILES``
(QoS-профиль ``_STATE`` и прежний хардкод ``queue_type == "system"``): для "state"
вердикт одинаков — груз роняемый.
"""

import queue as _queue

import pytest

from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry


def _registry(qos_profiles: bool, qtype: str, maxsize: int = 1, prefill: int = 1):
    """QueueRegistry с процессом 'gui' и его очередью ``qtype`` (предзаполненной)."""
    psr = ProcessStateRegistry()
    psr.register_process("gui")
    q = _queue.Queue(maxsize=maxsize)
    for i in range(prefill):
        q.put({"old": i})
    psr.add_queue("gui", qtype, q)
    reg = QueueRegistry(process_state_registry=psr, qos_profiles=qos_profiles)
    reg.initialize()
    return reg, q


class TestStateQueueDropsOldest:
    """state-очередь роняет старейшее (drop_oldest), не блокирует как system."""

    @pytest.mark.parametrize("qos_profiles", [False, True])
    def test_full_state_queue_evicts_not_blocks(self, qos_profiles):
        """Полная state-очередь → drop_oldest: доставка проходит, ``data_evicted``
        растёт, ``system_evict_blocked`` не трогается (на обоих путях флага)."""
        reg, q = _registry(qos_profiles, "state")

        ok = reg.send_to_queue("gui", "state", {"command": "state.changed", "n": 1})

        assert ok is True  # старый вытеснен, новый вошёл
        assert reg.data_evicted == 1
        assert reg.system_evict_blocked == 0
        # в очереди остался только новый конверт
        assert q.qsize() == 1
        assert q.get_nowait()["n"] == 1

    @pytest.mark.parametrize("qos_profiles", [False, True])
    def test_system_still_never_drops(self, qos_profiles):
        """Контраст: та же перегрузка на system-очереди БЛОКИРУЕТ вытеснение
        (never-drop) — доставки нет, ``system_evict_blocked`` растёт, ``data_evicted``
        не трогается. Гарантия, что раскол очередей не ослабил control-plane."""
        reg, _q = _registry(qos_profiles, "system")

        ok = reg.send_to_queue("gui", "system", {"command": "process.stop"})

        assert ok is False
        assert reg.system_evict_blocked == 1
        assert reg.data_evicted == 0
