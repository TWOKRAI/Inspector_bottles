# -*- coding: utf-8 -*-
"""Task 0.1 (план transport-single-policy) — счётчики «дверей» в очередь процесса.

Одна и та же очередь доступна двумя путями с РАЗНОЙ политикой переполнения:

- **канальная дверь** — ``_do_send`` → ``channel.send()`` → голый ``put`` без QoS;
- **targets-дверь** — ``_deliver_by_targets`` → ``QueueRegistry.send_to_queue``
  с drop_oldest, счётчиками и хуком ``on_evict``.

Пока обе двери живы, распределение трафика должно быть наблюдаемым: иначе
унификацию (Task 1.2) нечем доказать до, и нечем показать после, что дверь
осталась одна. Эти тесты фиксируют сам факт учёта, не поведение доставки.
"""

from __future__ import annotations

from queue import Queue

from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager


class _FakeQR:
    """Минимальный queue_registry: targets-доставка всегда успешна."""

    def __init__(self):
        self.sent: list = []

    def send_to_queue(self, process, qtype, msg, timeout: float = 0.0, on_evict=None):
        self.sent.append((process, qtype, msg))
        return True

    def get_queue(self, process, qtype):
        return None


def _router(**kw) -> RouterManager:
    return RouterManager(manager_name="seg", queue_registry=_FakeQR(), **kw)


class TestDoorAttribution:
    """Каждое сообщение учитывается ровно одной дверью."""

    def test_channel_door_is_counted(self):
        rm = _router()
        rm.register_channel(QueueChannel("seg_data", Queue()))
        rm.send({"type": "data", "channel": "seg_data", "data": 1})

        stats = rm.get_stats()["router"]
        assert stats["sent_via_channel"] == 1
        assert stats["sent_via_targets"] == 0

    def test_targets_door_is_counted(self):
        """Канал не резолвится → доставка по targets (дверь с политикой)."""
        rm = _router()
        rm.send({"type": "data", "targets": ["lines"], "data": 1})

        stats = rm.get_stats()["router"]
        assert stats["sent_via_targets"] == 1
        assert stats["sent_via_channel"] == 0

    def test_doors_are_mutually_exclusive_over_many_sends(self):
        """Сумма по дверям == числу доставленных, без двойного учёта."""
        rm = _router()
        rm.register_channel(QueueChannel("seg_data", Queue()))
        for _ in range(3):
            rm.send({"type": "data", "channel": "seg_data", "data": 1})
        for _ in range(2):
            rm.send({"type": "data", "targets": ["lines"], "data": 1})

        stats = rm.get_stats()["router"]
        assert stats["sent_via_channel"] == 3
        assert stats["sent_via_targets"] == 2

    def test_kind_breakdown_is_recorded(self):
        """Разбивка по kind нужна, чтобы отличить кадры от команд/телеметрии."""
        rm = _router()
        rm.register_channel(QueueChannel("seg_data", Queue()))
        rm.send({"type": "data", "channel": "seg_data", "data": 1})

        stats = rm.get_stats()["router"]
        assert stats.get("sent_via_channel.data") == 1

    def test_unknown_kind_does_not_break_delivery(self):
        """Разбивка best-effort: неизвестный тип не должен ронять отправку."""
        rm = _router()
        rm.register_channel(QueueChannel("seg_data", Queue()))
        result = rm.send({"type": "нет-такого-типа", "channel": "seg_data", "data": 1})

        assert result.get("status") == "success"
        assert rm.get_stats()["router"]["sent_via_channel"] == 1


class TestQueueChannelPutTimeout:
    """Потеря на канальной двери должна быть видимой, а не молчаливой."""

    def test_full_queue_increments_put_timeout(self):
        ch = QueueChannel("seg_data", Queue(maxsize=1))
        assert ch.send({"n": 1})["status"] == "success"

        result = ch.send({"n": 2}, timeout=0.05)  # очередь полна — put упрётся в timeout

        assert result["status"] == "error"
        assert ch.put_timeout_total == 1
        assert ch.send_errors == 1

    def test_successful_send_does_not_count(self):
        ch = QueueChannel("seg_data", Queue(maxsize=4))
        ch.send({"n": 1})
        assert ch.put_timeout_total == 0
        assert ch.send_errors == 0

    def test_counters_exposed_in_get_info(self):
        ch = QueueChannel("seg_data", Queue(maxsize=1))
        ch.send({"n": 1})
        ch.send({"n": 2}, timeout=0.05)

        info = ch.get_info()
        assert info["put_timeout_total"] == 1
        assert info["send_errors"] == 1

    def test_router_aggregates_channel_put_timeouts(self):
        """Роутер суммирует счётчики каналов — та же схема, что у frame-middleware."""
        rm = _router()
        rm.register_channel(QueueChannel("seg_data", Queue(maxsize=1)))
        rm.register_channel(QueueChannel("seg_system", Queue(maxsize=1)))
        rm.send({"type": "data", "channel": "seg_data", "data": 1})
        rm.send({"type": "data", "channel": "seg_data", "data": 2})

        assert rm.get_stats()["router"]["channel_put_timeouts"] >= 1
