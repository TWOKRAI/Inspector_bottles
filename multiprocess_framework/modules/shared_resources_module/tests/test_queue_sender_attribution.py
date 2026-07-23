"""«Кто душит очередь X» — учёт put'ов/потерь по отправителю (Ф4 Task 4.3).

План: `plans/truth-holes-closure.md`. Дыра: счётчики очереди отвечали «сколько
потеряно», но не «чей груз её забивает» — а разбор затора начинается именно с
этого вопроса; плюс ``never_drop_loss_total`` жил ТОЛЬКО внутри stdlib-лога и был
недоступен интроспекции (самая тяжёлая потеря системы — невидима для инструмента).

Проверяем: атрибуция put'ов и потерь, ограниченная кардинальность (память не течёт),
экспозиция обоих сигналов в ``get_stats``.
"""

import queue as _queue

from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry


def _registry(maxsize: int = 4, prefill: int = 0, qtype: str = "system"):
    psr = ProcessStateRegistry()
    psr.register_process("consumer")
    q = _queue.Queue(maxsize=maxsize)
    for i in range(prefill):
        q.put(f"старый-{i}")
    psr.add_queue("consumer", qtype, q)
    reg = QueueRegistry(process_state_registry=psr)
    reg.initialize()
    return reg, q


class TestSenderAttribution:
    def test_puts_counted_per_sender(self):
        reg, _q = _registry()
        reg.send_to_queue("consumer", "system", {"sender": "ProcessManager", "cmd": "a"})
        reg.send_to_queue("consumer", "system", {"sender": "ProcessManager", "cmd": "b"})
        reg.send_to_queue("consumer", "system", {"sender": "camera_0", "cmd": "c"})

        senders = reg.get_sender_stats("consumer_system")["consumer_system"]
        assert senders["ProcessManager"]["put"] == 2
        assert senders["camera_0"]["put"] == 1
        # Топ-виновник читается прямо из снимка — это и есть ответ «кто душит».
        assert max(senders, key=lambda s: senders[s]["put"]) == "ProcessManager"

    def test_loss_attributed_to_the_same_sender(self):
        """Полная never-drop очередь: потеря записана ТОМУ, чей груз пропал."""
        reg, _q = _registry(maxsize=1, prefill=1)
        ok = reg.send_to_queue("consumer", "system", {"sender": "ProcessManager", "cmd": "stop"})
        assert ok is False

        entry = reg.get_sender_stats()["consumer_system"]["ProcessManager"]
        assert entry["put"] == 1  # попытка учтена
        assert entry["lost"] == 1  # и её исход тоже

    def test_successful_send_has_no_loss(self):
        """Плечо пары: доставка прошла → put растёт, lost остаётся нулём."""
        reg, _q = _registry()
        reg.send_to_queue("consumer", "system", {"sender": "gui", "cmd": "ping"})
        entry = reg.get_sender_stats()["consumer_system"]["gui"]
        assert (entry["put"], entry["lost"]) == (1, 0)

    def test_anonymous_sender_is_named_not_dropped(self):
        """Груз без ``sender`` (не-dict/без поля) учитывается как ``__unknown__``.

        Пропускать такие put'ы нельзя: сумма разошлась бы с реальным трафиком, и
        «мы не знаем, кто» читалось бы как «никто не слал».
        """
        reg, _q = _registry()
        reg.send_to_queue("consumer", "system", "просто строка")
        reg.send_to_queue("consumer", "system", {"cmd": "без отправителя"})
        assert reg.get_sender_stats()["consumer_system"][QueueRegistry._SENDER_UNKNOWN]["put"] == 2

    def test_queues_are_counted_separately(self):
        psr = ProcessStateRegistry()
        psr.register_process("consumer")
        psr.add_queue("consumer", "system", _queue.Queue(maxsize=4))
        psr.add_queue("consumer", "data", _queue.Queue(maxsize=4))
        reg = QueueRegistry(process_state_registry=psr)
        reg.initialize()

        reg.send_to_queue("consumer", "system", {"sender": "pm"})
        reg.send_to_queue("consumer", "data", {"sender": "pm"})
        stats = reg.get_sender_stats()
        assert stats["consumer_system"]["pm"]["put"] == 1
        assert stats["consumer_data"]["pm"]["put"] == 1


class TestCardinalityCap:
    """Память не течёт при трафике со случайными именами отправителей."""

    def test_beyond_cap_goes_to_other_bucket(self):
        reg, _q = _registry(maxsize=1000)
        cap = QueueRegistry._SENDER_CARDINALITY_CAP
        for i in range(cap + 10):
            reg.send_to_queue("consumer", "system", {"sender": f"s{i}"})

        senders = reg.get_sender_stats()["consumer_system"]
        assert len(senders) == cap + 1  # cap имён + общее ведро
        assert senders[QueueRegistry._SENDER_OTHER_BUCKET]["put"] == 10

    def test_known_sender_still_counted_after_cap(self):
        """Уже известный отправитель продолжает считаться точно и после потолка."""
        reg, _q = _registry(maxsize=1000)
        reg.send_to_queue("consumer", "system", {"sender": "ProcessManager"})
        for i in range(QueueRegistry._SENDER_CARDINALITY_CAP + 5):
            reg.send_to_queue("consumer", "system", {"sender": f"s{i}"})
        reg.send_to_queue("consumer", "system", {"sender": "ProcessManager"})

        assert reg.get_sender_stats()["consumer_system"]["ProcessManager"]["put"] == 2


class TestStatsExposure:
    def test_never_drop_loss_total_is_readable(self):
        """Потеря доступна инструменту, а не только stdlib-логу."""
        reg, _q = _registry(maxsize=1, prefill=1)
        for _ in range(3):
            reg.send_to_queue("consumer", "system", {"sender": "pm", "cmd": "stop"})

        assert reg.never_drop_loss_total == 3
        assert reg.get_stats()["queues"]["never_drop_loss_total"] == 3

    def test_senders_in_get_stats(self):
        reg, _q = _registry()
        reg.send_to_queue("consumer", "system", {"sender": "pm"})
        senders = reg.get_stats()["queues"]["senders"]
        assert senders["consumer_system"]["pm"]["put"] == 1

    def test_snapshot_is_a_copy(self):
        """Снимок не мутирует под читателем (и его правка не портит счётчики)."""
        reg, _q = _registry()
        reg.send_to_queue("consumer", "system", {"sender": "pm"})
        snap = reg.get_sender_stats()
        snap["consumer_system"]["pm"]["put"] = 999
        assert reg.get_sender_stats()["consumer_system"]["pm"]["put"] == 1

    def test_zero_traffic_gives_empty_not_missing(self):
        """Ничего не слали → пустой снимок (0 ≠ «нет счётчика»)."""
        reg, _q = _registry()
        assert reg.get_sender_stats() == {}
        assert reg.get_stats()["queues"]["never_drop_loss_total"] == 0
