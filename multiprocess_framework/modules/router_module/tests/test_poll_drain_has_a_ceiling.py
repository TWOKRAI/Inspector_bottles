# -*- coding: utf-8 -*-
"""Неблокирующий дренаж очереди имеет потолок (Ф7.х, M-5 ревью Ф7).

Прежняя редакция ``QueueChannel.poll(0)`` крутила ``get_nowait`` до ``Empty`` и
объяснялась так: «больше глубины очереди оттуда не достанешь». Ревью опровергло
это ЗАМЕРОМ: producer в том же процессе доливает быстрее, чем consumer читает, и
один вызов вынес **2.1 млн сообщений за 88 секунд**, не отдав управление ни разу.
Это livelock приёмного цикла — пока он внутри дренажа, не проверяется ни
``_running``, ни остальные каналы.

Сегодня от этого спасает ТОПОЛОГИЯ (в проде никто не подписан сам на себя), а не
механизм. Гарантия, держащаяся на раскладке, перестаёт держаться при первой её
смене — поэтому потолок ставится в самом дренаже.
"""

from __future__ import annotations

import queue
import threading
import time

from ..channels.queue_channel import QueueChannel


def _channel(maxsize: int = 0) -> QueueChannel:
    return QueueChannel("probe", queue.Queue(maxsize=maxsize))


class TestDrainReturnsEvenWhileTheProducerKeepsFeeding:
    def test_live_producer_does_not_hold_the_drain_forever(self) -> None:
        """Стенд ревью в уменьшенном виде: producer быстрее consumer'а.

        Без потолка вызов не возвращается, пока пишет producer, — тест ловит это
        дедлайном join, а не бесконечным ожиданием.
        """
        channel = _channel()
        stop = threading.Event()

        def _feed() -> None:
            while not stop.is_set():
                channel._queue.put({"n": 1})

        producer = threading.Thread(target=_feed, name="producer", daemon=True)
        producer.start()
        # Дать очереди набраться заведомо выше потолка.
        while channel._queue.qsize() < QueueChannel.POLL_DRAIN_CEILING * 2:
            time.sleep(0.001)

        box: dict = {}
        drainer = threading.Thread(target=lambda: box.update(got=len(channel.poll(0))), daemon=True)
        drainer.start()
        drainer.join(timeout=5.0)
        stop.set()
        producer.join(timeout=5.0)

        assert not drainer.is_alive(), "дренаж не вернулся при живом producer — потолка нет (livelock цикла приёма)"
        assert box["got"] == QueueChannel.POLL_DRAIN_CEILING

    def test_the_remainder_is_not_lost_it_waits_for_the_next_tick(self) -> None:
        """Потолок — это «дочитаем на следующем такте», а не «выбросим остаток»."""
        channel = _channel()
        total = QueueChannel.POLL_DRAIN_CEILING + 17
        for i in range(total):
            channel._queue.put({"n": i})

        first = channel.poll(0)
        second = channel.poll(0)

        assert len(first) == QueueChannel.POLL_DRAIN_CEILING
        assert len(second) == 17
        assert [m["n"] for m in first + second] == list(range(total)), "порядок нарушен — дренаж перестал быть FIFO"

    def test_ordinary_drain_never_touches_the_ceiling(self) -> None:
        """Обратная половина: на штатных глубинах потолок не меняет ничего."""
        channel = _channel()
        for i in range(200):
            channel._queue.put({"n": i})

        assert len(channel.poll(0)) == 200

    def test_explicit_max_items_wins_over_the_default(self) -> None:
        channel = _channel()
        for i in range(50):
            channel._queue.put({"n": i})

        assert len(channel.poll(0, max_items=10)) == 10
        assert len(channel.poll(0, max_items=-1)) == 40, "отрицательное = «без потолка», и это должно писаться явно"

    def test_a_stream_of_none_cannot_spin_the_drain_forever(self) -> None:
        """Потолок считает ВЫНУТОЕ, а не собранное.

        ``None`` из очереди в результат не попадает; счёт по длине списка оставил
        бы ровно ту же бесконечность, только на другом входе.
        """
        channel = _channel()
        for _ in range(QueueChannel.POLL_DRAIN_CEILING + 100):
            channel._queue.put(None)

        box: dict = {}
        drainer = threading.Thread(target=lambda: box.update(got=len(channel.poll(0))), daemon=True)
        drainer.start()
        drainer.join(timeout=5.0)

        assert not drainer.is_alive(), "поток из None крутит дренаж вечно — потолок считает не то"
        assert box["got"] == 0
        assert channel._queue.qsize() == 100, "вынуто не ровно столько, сколько разрешал потолок"
