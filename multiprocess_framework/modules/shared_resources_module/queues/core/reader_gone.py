# -*- coding: utf-8 -*-
"""Метка «читатель ушёл навсегда» и отпуск feeder'а писателя на выходе (ADR-SRM-016).

Проблема (L-2, источник #2, замер 2026-09-23): на системном стопе все процессы гаснут
параллельно. Писатель успел положить в очередь соседа кадр крупнее свободного места в
OS pipe, а сосед (читатель) уже вышел. EPIPE не приходит — read-конец держит каждый
процесс, получивший очередь, включая самого писателя. На выходе интерпретатора
``multiprocessing`` джойнит feeder-поток (``queues._finalize_join``) — навсегда.

Механизм:
  * :class:`ReaderGoneQueue` — ``multiprocessing.queues.Queue`` с межпроцессным
    ``Event``-меткой, которая едет ВМЕСТЕ с очередью через spawn-pickle (bundle,
    routing_map) — никакой новой проводки.
  * Владелец очереди (процесс, в чьём bundle ``queues`` она лежит) взводит метку при
    выходе ТОЛЬКО на системном стопе. Индивидуальный стоп/рестарт метку НЕ взводит:
    ``restart_process`` по умолчанию переиспользует те же очереди, и отпущенный
    посреди записи кадр испортил бы поток новому воплощению.
  * Писатель на выходе закрывает свои очереди с живым feeder'ом и ждёт, пока буфер
    не сольётся ИЛИ не появится метка. Таймера нет: немаркированная очередь ждётся
    так же, как ждал бы ``_finalize_join`` (медленный живой читатель получает всё —
    ревью Task 1.1 отвергло wall-clock отпуск, ADR-SRM-015). Ожидание идёт в хуке, то есть
    ДО ``util._exit_function`` — раньше, чем ждал бы ``_finalize_join``, но так же без срока.
"""

from __future__ import annotations

import multiprocessing
import time
from multiprocessing.queues import Queue as _MpQueue
from multiprocessing.queues import _sentinel  # type: ignore[attr-defined]
from typing import Iterable, List, Tuple

# Шаг перепроверки метки, пока feeder писателя ещё держит данные. Это не бюджет
# ожидания (его нет), а задержка реакции на метку, появившуюся после первого взгляда.
POLL_INTERVAL_S = 0.02


class ReaderGoneQueue(_MpQueue):
    """``mp.Queue`` + метка «читатель ушёл навсегда», переживающая spawn-pickle."""

    def __init__(self, maxsize: int = 0, *, ctx=None) -> None:
        ctx = ctx if ctx is not None else multiprocessing.get_context()
        super().__init__(maxsize, ctx=ctx)
        self._reader_gone = ctx.Event()
        self._released_at_exit = False

    def __getstate__(self):
        return (super().__getstate__(), self._reader_gone)

    def __setstate__(self, state) -> None:
        base_state, self._reader_gone = state
        self._released_at_exit = False
        super().__setstate__(base_state)

    def mark_reader_gone(self) -> None:
        self._reader_gone.set()

    def is_reader_gone(self) -> bool:
        return self._reader_gone.is_set()


def _buffered(q: ReaderGoneQueue) -> int:
    """Сколько сообщений ещё лежит в буфере feeder'а (не дошли до pipe).

    Это НЕ полное число потерь: то, что уже в pipe, и не больше одного сообщения,
    застрявшего в ``send``, теряются без счёта — отсюда их не видно."""
    with q._notempty:  # feeder снимает элементы из буфера под этим же условием
        return sum(1 for item in q._buffer if item is not _sentinel)


def release_feeders_at_exit(
    own_queues: Iterable[object],
    all_queues: Iterable[object],
    system_stop: bool,
    poll_interval_s: float = POLL_INTERVAL_S,
) -> Tuple[int, int]:
    """Выходной хук процесса. Возвращает ``(отпущено очередей, сообщений из буфера feeder'а)``.

    Второе число — только то, что ещё лежало в буфере feeder'а отпущенных очередей.
    Уже записанное в pipe и не больше одного сообщения в полёте теряются без счёта.

    ``own_queues`` — очереди, которыми процесс владеет (читает их он); ``all_queues`` —
    все очереди, известные процессу (свои + соседи из routing_map). Очереди не
    :class:`ReaderGoneQueue` (созданные мимо реестра) не трогаются — у них остаётся
    штатный ``_finalize_join``.

    Блокирует, пока у немаркированной очереди feeder не сольёт буфер — ровно как
    блокировал бы выход интерпретатора без этого хука. Повторный вызов безопасен:
    уже отпущенные и уже слитые очереди пропускаются.
    """
    if system_stop:
        for q in own_queues:
            if isinstance(q, ReaderGoneQueue):
                q.mark_reader_gone()

    pending: List[ReaderGoneQueue] = []
    seen = set()
    for q in all_queues:
        if not isinstance(q, ReaderGoneQueue) or id(q) in seen:
            continue
        seen.add(id(q))
        thread = q._thread
        if thread is None or not thread.is_alive() or q._released_at_exit:
            continue
        # close(): sentinel в буфер — feeder выйдет сам, дописав всё до него. Это то
        # же, что сделал бы финализатор _finalize_close на выходе, только раньше.
        q.close()
        pending.append(q)

    released = buffered_dropped = 0
    while pending:
        still: List[ReaderGoneQueue] = []
        for q in pending:
            if not q._thread.is_alive():
                continue  # буфер слит — доставлено
            if q.is_reader_gone():
                buffered_dropped += _buffered(q)
                q.cancel_join_thread()
                q._released_at_exit = True
                released += 1
                continue
            still.append(q)
        pending = still
        if pending:
            time.sleep(poll_interval_s)
    return released, buffered_dropped
