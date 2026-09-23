# -*- coding: utf-8 -*-
"""Отпуск очередей на выходе процесса (Task 1.1 `plans/lifecycle-graceful-stop.md`).

Проблема: после teardown CPython на выходе (``multiprocessing.util._exit_function``
→ ``_run_finalizers`` → ``Queue._finalize_join``) ждёт feeder-поток КАЖДОЙ
``mp.Queue``, в которую процесс писал. Feeder, застрявший в ``send_bytes`` на
полном pipe без читателя, не вернётся никогда — процесс висит, пока спавнер его
не убьёт.

Решение (ADR-SRM-015):

1. Известным очередям с запущенным feeder'ом — ``close()`` (sentinel в буфер:
   feeder дожимает накопленное и выходит).
2. Все живые feeder'ы процесса — и известных очередей, и «сиротские» (объект
   очереди уже собран GC, а поток и его ``_finalize_join`` остались; замер на
   ``inspection_full``: именно такой висел в ProcessManager) — ждём под ОДНИМ
   общим дедлайном на всех.
3. Кто не дожал к дедлайну — снимаем его ``_finalize_join``: выход его больше
   не ждёт, недожатое в буфере теряется (число «брошено» в строке лога).
"""

from __future__ import annotations

import time
from multiprocessing import queues as _mp_queues
from multiprocessing import util as _mp_util
from typing import Callable, Iterable, List, Tuple

# Общий бюджет на ВСЕ feeder'ы процесса, секунды (замер — ADR-SRM-015).
EXIT_RELEASE_BUDGET_S = 0.25


def _feeder_thread(queue):
    # Приватный атрибут CPython: публичного способа узнать, запущен ли feeder в
    # ЭТОМ процессе, нет. Нужен, чтобы не закрывать очереди, из которых процесс
    # только читает (close() делает get() → ValueError). См. ADR-SRM-015.
    return getattr(queue, "_thread", None)


def _orphan_feeders(known_threads: set) -> List[Tuple[object, Callable[[], None]]]:
    """Живые feeder'ы, до чьих очередей не добраться (объект очереди собран GC).

    Приватное API CPython (``util._finalizer_registry``, ``Finalize._callback`` /
    ``_args``): у сироты не осталось ничего, кроме записи ``_finalize_join`` в
    реестре финализаторов. ``Finalize.cancel()`` — её публичный метод.
    """
    found = []
    registry = getattr(_mp_util, "_finalizer_registry", None) or {}
    for fin in list(registry.values()):
        try:
            if getattr(fin, "_callback", None) is not _mp_queues.Queue._finalize_join:
                continue
            thread = fin._args[0]()
            if thread is None or id(thread) in known_threads or not thread.is_alive():
                continue
            found.append((thread, fin.cancel))
        except Exception:  # noqa: BLE001
            continue
    return found


def release_queues_at_exit(queues: Iterable, budget_s: float = EXIT_RELEASE_BUDGET_S) -> Tuple[int, int]:
    """Дать feeder'ам дожать данные за ``budget_s`` суммарно, остальных отпустить.

    Возвращает ``(дожато, брошено)`` — число feeder'ов, завершившихся до
    дедлайна, и число отпущенных (выход их больше не ждёт). Очереди без
    feeder'а (процесс в них не писал) не считаются и не трогаются. Не бросает.
    """
    deadline = time.monotonic() + max(0.0, budget_s)
    seen: set[int] = set()
    pending: List[Tuple[object, Callable[[], None]]] = []
    try:
        for queue in queues:
            if id(queue) in seen:
                continue
            seen.add(id(queue))
            try:
                thread = _feeder_thread(queue)
                if thread is None or not hasattr(queue, "cancel_join_thread"):
                    continue
                queue.close()
                pending.append((thread, queue.cancel_join_thread))
            except Exception:  # noqa: BLE001 — одна очередь не валит остальные
                pass
    except Exception:  # noqa: BLE001 — сломанный итератор: отпускаем собранное
        pass
    try:
        pending.extend(_orphan_feeders({id(t) for t, _ in pending}))
    except Exception:  # noqa: BLE001
        pass

    drained = abandoned = 0
    for thread, release in pending:
        try:
            thread.join(max(0.0, deadline - time.monotonic()))
            if not thread.is_alive():
                drained += 1
                continue
        except Exception:  # noqa: BLE001
            pass
        try:
            release()
        except Exception:  # noqa: BLE001
            pass
        abandoned += 1
    return drained, abandoned
