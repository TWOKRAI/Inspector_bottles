# -*- coding: utf-8 -*-
"""Task 4.7c (C1) — тесты автора на опасные места выборочного удаления из chain_queue.

Слепой tester пинит контракт «потолок считает кадры». Здесь то, что видно только изнутри построения
``DataReceiver._bound_lag``: удаление из середины ``queue.Queue`` идёт под ``mutex`` в обход
``get()``, и два риска сидят именно там — (а) гонка с потребителем и потерянный сигнал
``not_full`` (производитель, блокированный в ``put()``, не проснётся), (б) очередь на пределе
``maxsize``, забитая одними сигналами, которые потолок вытеснять не вправе.

Всё, что может заблокироваться, идёт в daemon-потоке с дедлайном join: зависший тест хуже отсутствующего.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import queue
import threading
import time

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver


def _receiver(chain: queue.Queue, max_lag: int) -> DataReceiver:
    return DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=None,
        item_collector=object(),
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        max_lag_items=max_lag,
    )


def _frame(marker: str) -> list[dict]:
    return [{"marker": marker, "frame": 0}]


def _signal(marker: str) -> list[dict]:
    return [{"marker": marker, "command": "draw"}]


def test_removal_under_mutex_with_a_blocked_producer_does_not_deadlock():
    """Очередь на пределе (maxsize 1) с кадром f1; производитель висит в блокирующем ``put`` на ``not_full``;
    потолок (1) в другом потоке выбрасывает f1 под mutex и кладёт f2.

    Что здесь доказано честно: взаимной блокировки нет (``put_nowait`` не зовётся под mutex — Lock
    нереентерантный), и после ОДНОГО get() потребителя завершаются оба писателя. Чего здесь доказать
    нельзя: необходимость ``not_full.notify`` — при естественной вставке чистое изменение числа
    занятых мест 0 (убрали один, положили один), освободившееся место сразу занимает сам потолок;
    это держит параллельный тест ниже (потерянный сигнал = зависший производитель) и инъекция
    поломки (убрать notify) у лида.
    """
    chain: queue.Queue = queue.Queue(maxsize=1)
    bound = _receiver(chain, max_lag=1)
    bound.on_items_ready(_frame("f1"))

    put_done = threading.Event()

    def blocked_producer() -> None:
        chain.put(_signal("sig"))
        put_done.set()

    producer = threading.Thread(target=blocked_producer, daemon=True)
    producer.start()
    time.sleep(0.2)
    assert not put_done.is_set(), "стенд неисправен: put не заблокировался на полной очереди"

    bound_done = threading.Event()

    def bound_put() -> None:
        bound.on_items_ready(_frame("f2"))
        bound_done.set()

    t = threading.Thread(target=bound_put, daemon=True)
    t.start()
    time.sleep(0.3)
    # Кто-то из двоих занял освободившееся место, второй ждёт get(): один get() обязан довести обоих.
    assert bound.lag_dropped_total == 1
    taken = chain.get(timeout=5.0)[0]["marker"]
    assert taken in ("sig", "f2")
    t.join(5.0)
    producer.join(5.0)
    assert bound_done.is_set(), "on_items_ready повис на выборочном удалении (взаимная блокировка)"
    assert put_done.is_set(), "блокированный производитель не завершил put"
    assert chain.get(timeout=5.0)[0]["marker"] in ("sig", "f2")


def test_concurrent_consumer_get_and_selective_removal_lose_nothing():
    """Потребитель get() в одном потоке, потолок с выборочным удалением в другом, 2000 кадров и 2000 сигналов.

    Свойства: (1) ни один сигнал не потерян (потолок их не вытесняет; потребитель их выбрал бы все),
    (2) кадры: принятые + выброшенные потолком == отправленные (не потеряно и не размножено),
    (3) всё завершается в дедлайн — без взаимной блокировки на mutex/not_full.
    """
    n = 2000
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=4)
    consumed: list[str] = []
    stop = threading.Event()

    def consumer() -> None:
        while not stop.is_set() or not chain.empty():
            try:
                consumed.append(chain.get(timeout=0.02)[0]["marker"])
            except queue.Empty:
                continue

    def producer() -> None:
        for i in range(n):
            receiver.on_items_ready(_frame(f"f{i}"))
            receiver.on_items_ready(_signal(f"s{i}"))

    c = threading.Thread(target=consumer, daemon=True)
    p = threading.Thread(target=producer, daemon=True)
    c.start()
    p.start()
    p.join(30.0)
    assert not p.is_alive(), "производитель завис (потерянный notify или взаимная блокировка)"
    stop.set()
    c.join(10.0)
    assert not c.is_alive(), "потребитель завис"

    signals = [m for m in consumed if m.startswith("s")]
    frames = [m for m in consumed if m.startswith("f")]
    assert signals == [f"s{i}" for i in range(n)], "сигнал потерян или порядок сигналов нарушен"
    assert len(frames) + receiver.lag_dropped_total == n, (len(frames), receiver.lag_dropped_total)
    assert len(set(frames)) == len(frames), "кадр размножен"
    assert frames == sorted(frames, key=lambda m: int(m[1:])), "порядок кадров нарушен"


def test_queue_at_chain_maxsize_with_only_signals_is_not_dropped():
    """Очередь на пределе maxsize 3 забита ОДНИМИ сигналами; потолок кадров 1.

    Приходит кадр: кадровых в очереди 0 < потолка -> удалять нечего, сигналы остаются; место занято ->
    put_nowait падает Full -> прежняя блокирующая дорога (не тихая потеря и не вытеснение сигнала).
    Кадр ждёт места; после get() сигнала — укладывается. Счётчик потолка 0, сигналы целы.
    """
    chain: queue.Queue = queue.Queue(maxsize=3)
    receiver = _receiver(chain, max_lag=1)
    for i in range(3):
        receiver.on_items_ready(_signal(f"s{i}"))
    assert chain.qsize() == 3

    done = threading.Event()

    def put_frame() -> None:
        receiver.on_items_ready(_frame("f"))
        done.set()

    t = threading.Thread(target=put_frame, daemon=True)
    t.start()
    assert not done.wait(0.3), "кадр прошёл на полную очередь сигналов — сигнал был вытеснен"
    assert receiver.lag_dropped_total == 0
    assert list(chain.queue)[0][0]["marker"] == "s0"

    first = chain.get_nowait()[0]["marker"]  # освободили место
    assert first == "s0"
    assert done.wait(5.0), "кадр не уложился после освобождения места"
    t.join(2.0)

    drained = []
    while True:
        try:
            drained.append(chain.get_nowait()[0]["marker"])
        except queue.Empty:
            break
    assert drained == ["s1", "s2", "f"]
    assert receiver.lag_dropped_total == 0
