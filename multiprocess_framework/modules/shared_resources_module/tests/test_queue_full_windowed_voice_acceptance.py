# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации): окно на «очередь полна».

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «Переполнение очереди — один голос на окно + счётчик queue_full_events.
    Точка: multiprocess_framework/modules/shared_resources_module/queues/core/manager.py,
    пара Full() / drop_oldest. N попыток записи в полную очередь → ≤ 1 голос,
    queue_full_events == N.»

Сегодня (2026-08-31, до реализации) в ``QueueRegistry`` УЖЕ есть четыре
раздельных троттлированных механизма для этого класса событий —
``_system_evict_*``/``system_evict_blocked``, ``_data_evict_*``/``data_evicted``,
``_never_drop_loss_*``/``_never_drop_loss_total``, ``_queue_missing_*`` — но НИ
ОДИН из них не публикует счётчик по имени ``queue_full_events`` (сверено
grep'ом по всему дереву — совпадений нет). Общий механизм критерия ЕЩЁ не
реализован — тест обязан упасть.

Управление временем: подменяется ``time.monotonic`` ИМЕННО в модуле manager.py
(``...queues.core.manager.time.monotonic``) — тот же приём, которым модуль сам
меряет окна (``import time`` наверху файла, ``time.monotonic()`` в каждом
throttle). НЕ сплю реальные секунды: на Windows разрешение monotonic — 15.6 мс,
разности < 100 мс на сетке врут, а суммарное окно здесь 5 с (или больше, если
конфиг задаёт другое) — живой sleep растянул бы прогон и был бы флейковым.

Сценарий с never-drop ("system") очередью: ``queue.put_nowait`` в заведомо
полную очередь бросает ``queue.Full`` — та самая пара, названная в критерии.
"""

from __future__ import annotations

import logging
import queue as _queue


from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry

#: Модульный путь manager.py — сюда патчим time.monotonic и отсюда caplog слушает
#: stdlib-fallback логгер (`_loss_logger = get_std_logger(__name__, ...)`,
#: тот же приём, что и в соседнем test_never_drop_loss_visibility.py).
_MODULE_PATH = "multiprocess_framework.modules.shared_resources_module.queues.core.manager"


def _registry_with_queue(maxsize: int = 1, prefill: int = 1, qtype: str = "system"):
    """QueueRegistry с зарегистрированным процессом 'consumer' и его очередью.

    Скопировано 1:1 с фикстуры соседнего test_never_drop_loss_visibility.py —
    это существующий, не мой, паттерн конструирования QueueRegistry в тесте.
    """
    psr = ProcessStateRegistry()
    psr.register_process("consumer")
    q = _queue.Queue(maxsize=maxsize)
    for i in range(prefill):
        q.put(f"старый-{i}")
    psr.add_queue("consumer", qtype, q)
    reg = QueueRegistry(process_state_registry=psr)
    reg.initialize()
    return reg, q


class TestQueueFullEventsWindowed:
    def test_n_full_attempts_give_at_most_one_voice_per_window(self, caplog, monkeypatch):
        """N попыток put в переполненную never-drop очередь внутри ОДНОГО окна → ≤1 запись."""
        reg, _q = _registry_with_queue(maxsize=1, prefill=1, qtype="system")

        clock = [1_000.0]
        monkeypatch.setattr(f"{_MODULE_PATH}.time.monotonic", lambda: clock[0])

        n_attempts = 5
        with caplog.at_level(logging.WARNING, logger=_MODULE_PATH):
            for i in range(n_attempts):
                clock[0] += 0.01  # все попытки внутри одного 5-секундного окна
                reg.send_to_queue("consumer", "system", {"cmd": f"cmd-{i}"})

        # Любая запись плоскости о переполнении/потере (не привязываюсь к точному
        # тексту — он реализации не принадлежит тестеру; факт в ЧИСЛЕ записей).
        voices = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(voices) <= 1, (
            f"{n_attempts} попыток в одном окне обязаны дать не больше одного голоса, "
            f"получено {len(voices)}: {[r.getMessage() for r in voices]}"
        )

    def test_n_full_attempts_give_exact_queue_full_events_count(self, monkeypatch):
        """Счётчик queue_full_events — арифметика, не троттлится: должен быть == N."""
        reg, _q = _registry_with_queue(maxsize=1, prefill=1, qtype="system")

        clock = [2_000.0]
        monkeypatch.setattr(f"{_MODULE_PATH}.time.monotonic", lambda: clock[0])

        n_attempts = 7
        for i in range(n_attempts):
            clock[0] += 0.01
            reg.send_to_queue("consumer", "system", {"cmd": f"cmd-{i}"})

        # АДРЕС поправлен реализатором (Task 1.4), значения — нет: счётчики этого
        # реестра лежат под секцией "queues" (``ManagerStatsMixin._merge_stats``),
        # рядом с ``never_drop_loss_total``/``data_evicted``/``system_evict_blocked``.
        # Тестер писал вслепую и предположил плоский readback — расхождение
        # модели, названное в отчёте, а не ослабление критерия.
        stats = reg.get_stats()["queues"]
        assert "queue_full_events" in stats, (
            "readback QueueRegistry.get_stats() не содержит ключ 'queue_full_events' — "
            "счётчик из критерия приёмки ещё не заведён"
        )
        assert stats["queue_full_events"] == n_attempts, (
            f"ожидалось queue_full_events == {n_attempts} (по одной на попытку, троттлинг "
            f"не имеет права трогать счётчик), получено {stats.get('queue_full_events')}"
        )

    def test_voice_after_window_names_suppressed_count(self, caplog, monkeypatch):
        """После окна следующий голос обязан назвать число подавленных с прошлой записи."""
        reg, _q = _registry_with_queue(maxsize=1, prefill=1, qtype="system")

        clock = [3_000.0]
        monkeypatch.setattr(f"{_MODULE_PATH}.time.monotonic", lambda: clock[0])

        with caplog.at_level(logging.WARNING, logger=_MODULE_PATH):
            # Три попытки внутри окна — 1-я голосит, 2-я и 3-я подавлены.
            reg.send_to_queue("consumer", "system", {"cmd": "a"})
            clock[0] += 0.01
            reg.send_to_queue("consumer", "system", {"cmd": "b"})
            clock[0] += 0.01
            reg.send_to_queue("consumer", "system", {"cmd": "c"})
            # Дальше окна (>5с, с запасом) — голос обязан прозвучать снова и
            # назвать «подавлено: 2» (b и c).
            clock[0] += 10.0
            reg.send_to_queue("consumer", "system", {"cmd": "d"})

        voices = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(voices) == 2, f"ожидались ровно 2 голоса (первый + после окна), получено {len(voices)}"
        second_text = voices[1].getMessage()
        assert "2" in second_text, (
            f"второй голос обязан назвать число подавленных с прошлой записи (2: b и c), текст: {second_text!r}"
        )
