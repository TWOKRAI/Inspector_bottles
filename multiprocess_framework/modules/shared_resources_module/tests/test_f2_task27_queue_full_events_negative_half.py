# -*- coding: utf-8 -*-
"""Task 2.7 плана observability-closure (добор ревью Ф1) — независимый тестер.

Критерий приёмки 1 (текст задачи, передан координатором; план ``phase-2-one-policy.md``
и реализация мне не показаны):

    «Пара на queue_full_events: тест "очередь реально переполнена → счётчик вырос
    ровно на число событий (литерал)" И тест "серия УСПЕШНЫХ отправок, переполнения
    нет → счётчик НЕ изменился (дельта == 0)". Второй — тот, которого не было.»

Первая половина пары уже существует и зелёная —
``test_queue_full_windowed_voice_acceptance.py::TestQueueFullEventsWindowed::
test_n_full_attempts_give_exact_queue_full_events_count`` (задача Task 1.4). Этот
файл добавляет ИМЕННО отсутствовавшую половину: серия успешных
``QueueRegistry.send_to_queue`` в НЕполную очередь не имеет права тронуть
``queue_full_events``.

**Дисклеймер по красноте — важно прочитать перед тем, как судить прогон.**
Ревью фазы Ф1 (``plans/observability-closure/review-phase-1.md``, находка 1)
воспроизвело ОТСУТСТВИЕ этой половины ЗАПЛАТКОЙ: throwaway pytest-плагин,
monkeypatch-обёртка над ``send_to_queue``, искусственно ИНКРЕМЕНТИРУЮЩАЯ счётчик
на каждом успехе (``[ЗАПЛАТКА] ложных инкрементов queue_full_events сделано: 6447``
при 246 настоящих тестах). Это доказывает пробел в ПОКРЫТИИ (без такого теста
регрессия невидима), а НЕ то, что боевой код сегодня ведёт себя так без заплатки.

Прочитанный код (``queues/core/manager.py``, ``send_to_queue``) инкрементирует
``self._stats["queue_full_events"]`` СТРОГО внутри ``except Exception as e: if
isinstance(e, Full):`` — то есть уже сегодня, без единой правки реализации, успешный
``queue.put_nowait``/``put`` в эту ветку не заходит вовсе. Поэтому тест ниже ожидаемо
ЗЕЛЁН на этом коммите (0b2d5b15): он закрывает пробел в ТЕСТАХ, а не создаёт ТЗ для
новой реализации счётчика. Зелёный результат — находка сама по себе (закрывает
половину (б) критерия приёмки формально), названа в отчёте координатору отдельно,
а не спрятана за общим "красных N".
"""

from __future__ import annotations

import queue as _queue

from ..queues import QueueRegistry
from ..state.process_state_registry import ProcessStateRegistry


def _registry_with_room(maxsize: int = 16, qtype: str = "system"):
    """QueueRegistry с процессом 'consumer' и ПРОСТОРНОЙ (никогда не переполняемой
    в рамках теста) очередью — зеркало ``_registry_with_queue`` из соседнего
    acceptance-файла (Task 1.4), только без ``prefill``, чтобы put ВСЕГДА успевал.
    """
    psr = ProcessStateRegistry()
    psr.register_process("consumer")
    q = _queue.Queue(maxsize=maxsize)
    psr.add_queue("consumer", qtype, q)
    reg = QueueRegistry(process_state_registry=psr)
    reg.initialize()
    return reg, q


class TestQueueFullEventsIsAPair:
    """Правило проекта: у диагностического счётчика — ОБЕ половины пары."""

    def test_successful_sends_leave_queue_full_events_at_zero(self) -> None:
        """Ложноположительная половина: N успешных send_to_queue → дельта 0.

        ``n_attempts`` заведомо меньше ``maxsize`` очереди — переполнения не
        случится НИ РАЗУ, каждая попытка обязана вернуть True.
        """
        reg, q = _registry_with_room(maxsize=16)

        n_attempts = 12
        for i in range(n_attempts):
            ok = reg.send_to_queue("consumer", "system", {"cmd": f"cmd-{i}"})
            assert ok is True, f"попытка {i} обязана была успеть — очередь заведомо не полна (maxsize=16)"

        stats = reg.get_stats()["queues"]
        assert q.qsize() == n_attempts, (
            f"все {n_attempts} сообщений обязаны были реально лечь в очередь, фактический qsize={q.qsize()}"
        )
        assert stats.get("queue_full_events", 0) == 0, (
            f"queue_full_events вырос без единого переполнения: {stats.get('queue_full_events')} "
            f"после {n_attempts} успешных отправок — ложноположительная половина пары "
            f"(та самая, которой не было по находке ревью Ф1)"
        )

    def test_successful_sends_to_a_non_never_drop_queue_also_leave_it_at_zero(self) -> None:
        """Тот же факт на droppable-очереди (``data``, а не ``system``) — второй тип
        очереди в manager.py идёт другой веткой кода (``_is_never_drop`` разводит
        ``never_drop_loss``/``errors`` от общей арифметики), поэтому пара из одного
        типа очереди не покрывает вторую целиком."""
        reg, q = _registry_with_room(maxsize=16, qtype="data")

        n_attempts = 10
        for i in range(n_attempts):
            ok = reg.send_to_queue("consumer", "data", {"frame": i})
            assert ok is True, f"попытка {i} обязана была успеть — очередь заведомо не полна (maxsize=16)"

        stats = reg.get_stats()["queues"]
        assert stats.get("queue_full_events", 0) == 0, (
            f"queue_full_events вырос без единого переполнения на droppable-очереди: "
            f"{stats.get('queue_full_events')} после {n_attempts} успешных отправок"
        )
