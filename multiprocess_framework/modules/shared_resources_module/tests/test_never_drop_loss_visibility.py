"""Видимость безвозвратной потери never-drop груза (QueueRegistry.send_to_queue).

Контекст: на живом рецепте ProcessManager непрерывно терял ~17 сообщений/с в
полные system-очереди. Счётчики росли, но НИ ОДНА строка не доходила до логов —
у QueueRegistry в проде нет LoggerManager, поэтому self._log_* тихо возвращали
None. Здесь проверяется пара «потеря → запись с именем получателя» / «норма →
тишина» и обязательный троттлинг (26k событий не должны дать 26k строк).
"""

import logging
import queue as _queue
import time


from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry

#: Логгер, в который пишет QueueRegistry о потере (модульный stdlib-fallback).
_LOGGER_NAME = "multiprocess_framework.modules.shared_resources_module.queues.core.manager"

#: Сдвиг часов, заведомо больший ЛЮБОГО окна голоса (дефолт политики — 5.0 с).
#: Литерал, а не чтение действующей политики: тест, берущий ожидание из того же
#: источника, что и код, согласится с любым значением, включая ноль.
_BEYOND_ANY_WINDOW_SEC = 60.0


def _registry_with_queue(maxsize: int = 1, prefill: int = 1, qtype: str = "system"):
    """QueueRegistry с зарегистрированным процессом 'consumer' и его очередью."""
    psr = ProcessStateRegistry()
    psr.register_process("consumer")
    q = _queue.Queue(maxsize=maxsize)
    for i in range(prefill):
        q.put(f"старый-{i}")
    psr.add_queue("consumer", qtype, q)
    reg = QueueRegistry(process_state_registry=psr)
    reg.initialize()
    return reg, q


def _loss_records(caplog) -> list:
    return [r for r in caplog.records if "ПОТЕРЯ СООБЩЕНИЯ" in r.getMessage()]


class TestNeverDropLossVisible:
    """Пара ON/OFF: переполнение говорит, норма молчит."""

    def test_overflow_names_the_recipient(self, caplog):
        """Полная system-очередь → ERROR с именем получателя, типом и размером."""
        reg, q = _registry_with_queue()
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            ok = reg.send_to_queue("consumer", "system", {"cmd": "process.stop"})

        assert ok is False  # доставки не было
        records = _loss_records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert "consumer" in message  # ГЛАВНОЕ: кому не доехало
        assert "system" in message
        assert "БЕЗВОЗВРАТНО" in message
        assert "1" in message  # размер очереди

    def test_normal_send_is_silent(self, caplog):
        """Очередь не полна → доставка прошла, записи о потере нет."""
        reg, q = _registry_with_queue(maxsize=4, prefill=0)
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            ok = reg.send_to_queue("consumer", "system", {"cmd": "ping"})

        assert ok is True
        assert _loss_records(caplog) == []

    def test_droppable_queue_does_not_report_loss(self, caplog):
        """data-очередь вытесняет старое и доставляет — это не безвозвратная потеря."""
        reg, q = _registry_with_queue(qtype="data")
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            ok = reg.send_to_queue("consumer", "data", {"frame": 1})

        assert ok is True  # место освобождено вытеснением
        assert _loss_records(caplog) == []


class TestThrottling:
    """26 тысяч событий не должны дать 26 тысяч строк."""

    def test_many_losses_give_one_record(self, caplog):
        reg, q = _registry_with_queue()
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(50):
                reg.send_to_queue("consumer", "system", {"cmd": "stop"})

        assert len(_loss_records(caplog)) == 1  # не 50
        assert reg._never_drop_loss_total == 50  # но учтены все

    def test_window_expiry_allows_next_record(self, caplog, monkeypatch):
        """Истекло окно → следующая потеря снова говорит (глушитель не навсегда).

        Ф1.4: окно держит общий механизм (``logger_module.core.windowed_voice``),
        собственных ``_never_drop_loss_last_log``/``_NEVER_DROP_LOSS_LOG_INTERVAL_SEC``
        у реестра больше нет. Проверяемое свойство прежнее, сдвигается теперь не
        приватная метка, а ЧАСЫ — то есть ближе к настоящему истечению окна, чем
        было. Живого ``sleep`` по-прежнему нет: на Windows разрешение
        ``time.monotonic`` 15.6 мс, и разности меньше ~100 мс ложатся на сетку.
        """
        reg, q = _registry_with_queue()
        clock = [1_000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            reg.send_to_queue("consumer", "system", {"cmd": "stop"})
            clock[0] += _BEYOND_ANY_WINDOW_SEC
            reg.send_to_queue("consumer", "system", {"cmd": "stop"})

        assert len(_loss_records(caplog)) == 2

    def test_record_reports_rate_not_just_fact(self, caplog, monkeypatch):
        """Троттлированная запись называет темп: сколько потеряно с прошлой записи."""
        reg, q = _registry_with_queue()
        clock = [2_000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(10):
                reg.send_to_queue("consumer", "system", {"cmd": "stop"})
            clock[0] += _BEYOND_ANY_WINDOW_SEC
            reg.send_to_queue("consumer", "system", {"cmd": "stop"})

        records = _loss_records(caplog)
        assert len(records) == 2
        # Первая запись: 1 потеря к моменту записи. Вторая: 10 накопленных за окно.
        assert "всего: 11" in records[1].getMessage()
        # Ф1.4: и отдельно — ЧИСЛО подавленных с прошлой записи. Раньше эту
        # величину считал сам реестр (``_never_drop_loss_since_log``), теперь
        # механизм окна; свойство «запись называет темп, а не только факт»
        # обязано пережить переезд, иначе переезд его тихо съел.
        assert "Подавлено с прошлой записи: 9" in records[1].getMessage()


def test_loss_report_survives_missing_qsize(caplog, monkeypatch):
    """qsize() недоступен (macOS) — запись всё равно выходит, без размера."""
    reg, q = _registry_with_queue()

    def _boom():
        raise NotImplementedError("qsize недоступен на этой платформе")

    monkeypatch.setattr(q, "qsize", _boom)
    with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
        reg.send_to_queue("consumer", "system", {"cmd": "stop"})

    records = _loss_records(caplog)
    assert len(records) == 1
    assert "недоступен" in records[0].getMessage()


def test_registry_has_no_logger_in_production_shape():
    """Регресс-якорь диагноза: штатная плоскость логов у QueueRegistry пуста.

    Если однажды logger сюда всё-таки проведут — тест упадёт и напомнит, что
    stdlib-fallback стал дублировать штатный канал и его пора пересмотреть.
    """
    from ..core.shared_resources_manager import SharedResourcesManager

    srm = SharedResourcesManager(manager_name="shared_resources")  # как в spawner.py
    assert srm.queue_registry.has_manager("logger") is False
