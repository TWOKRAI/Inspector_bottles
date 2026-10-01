# -*- coding: utf-8 -*-
"""Task 4.7c rework — слепые RED-тесты условий C1 и C3 вердикта CTO для ``DataReceiver``.

Источник — docs/reviews/2026-10-01_task-4.7-cto-verdict.md; реализации в дереве нет по построению.

C1 (кадро-осознанный потолок отставания). Потолок ``max_lag_items`` считает ТОЛЬКО кадровые коллекции
(хотя бы один item несёт ``_shm_views`` или ``frame``); коллекция без кадра (сигнал: кнопка, команда)
потолком не вытесняется и в счёт не идёт. Репро вердикта: lag 2, один сигнал + две кадровые коллекции,
потом ещё кадр -> сигнал выжил, ``lag_dropped_total`` вырос на 1, порядок остальных сохранён.
Коллекция join, в которой сигнал склеен с кадром, — КАДРОВАЯ (семантика join по вердикту): её потолок
выбрасывает вместе с кадром. Обратное не пинится.

C3 (транзит измеряется, а не навязывается). Приёмник на каждом получении читает глубину IPC-очереди,
пишет её gauge'ом и увеличивает ``transit_over_budget``, когда глубина > B - lag.

ДОПУЩЕНИЯ (угаданные имена — в одном месте, ради диагностики; контракт дизайном не задан):
  * конструктор ``DataReceiver`` получает два новых kwarg'а: ``inflight_budget`` (B, int) и
    ``ipc_depth_fn`` (callable без аргументов -> текущая глубина IPC data-очереди). Порог транзита —
    ``B - max_lag_items`` (lag приёмник уже знает). Всё остальное в C3 — на литералах брифа;
  * счётчик читается как свойство ``receiver.transit_over_budget`` (по аналогии с
    ``lag_dropped_total``): публичного accessor'а счётчиков у приёмника нет;
  * gauge читается там, где приёмник уже отдаёт числа наружу: свойство ``ipc_queue_depth`` ИЛИ любое
    поле ``get_cycle_metrics()`` с «depth» в имени (хедж между двумя правдоподобными адресами —
    имя gauge'а брифом не задано).
Остальное (``on_items_ready``, ``lag_dropped_total``, ``run_loop``, ``get_cycle_metrics``) — существующие API.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import List

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.collector_registry import PassThroughCollector
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver


def _receiver(chain: queue.Queue, max_lag: int, **extra) -> DataReceiver:
    return DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=None,
        item_collector=PassThroughCollector(),
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        max_lag_items=max_lag,
        **extra,
    )


def _drain(chain: queue.Queue) -> List[str]:
    """Маркеры первых item'ов коллекций по порядку — судим по данным, а не по qsize."""
    out: List[str] = []
    while True:
        try:
            out.append(chain.get_nowait()[0]["marker"])
        except queue.Empty:
            return out


def _frame(marker: str) -> list[dict]:
    """Кадровая коллекция: item несёт настоящий ndarray в ``frame`` (не строку-заглушку)."""
    return [{"marker": marker, "frame": np.zeros((2, 2), dtype=np.uint8)}]


def _views(marker: str) -> list[dict]:
    """Кадровая коллекция другого вида: кадр едет как zero-copy view-ссылка, ключа ``frame`` нет."""
    ref = {"owner": "cam", "slot": "output_frames", "idx": 0, "gen": 2, "name": f"v_{marker}"}
    return [{"marker": marker, "_shm_views": [ref]}]


def _signal(marker: str) -> list[dict]:
    """Коллекция без кадра: кнопка/команда."""
    return [{"marker": marker, "command": "draw"}]


# =============================================================================
# C1. Потолок считает только кадровые коллекции
# =============================================================================


@pytest.mark.xfail(strict=True, reason="4.7c rework: C1")
def test_signal_survives_lag_bound():
    """Репро вердикта: lag 2; сигнал + кадры f1, f2, затем f3 -> выброшен самый старый КАДР (f1),
    сигнал на месте, порядок оставшихся сохранён, счётчик +1.

    Сегодня потолок считает сообщения: сигнал вытесняется уже при укладке f2 (остаются f1, f2), а на
    f3 уходит f1 — в очереди [f2, f3], выброшено 2."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=2)

    for coll in (_signal("sig"), _frame("f1"), _frame("f2"), _frame("f3")):
        receiver.on_items_ready(coll)

    assert _drain(chain) == ["sig", "f2", "f3"]
    assert receiver.lag_dropped_total == 1


@pytest.mark.xfail(strict=True, reason="4.7c rework: C1")
def test_only_frame_collections_counted():
    """lag 2 и десять сигналов подряд (кадров нет вовсе) -> не выброшен ни один: сигналы в счёт потолка
    не входят и им не вытесняются; порядок прежний.

    Сегодня очередь режется до 2 (остаются s8, s9), выброшено 8."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=2)

    for i in range(10):
        receiver.on_items_ready(_signal(f"s{i}"))

    assert _drain(chain) == [f"s{i}" for i in range(10)]
    assert receiver.lag_dropped_total == 0


@pytest.mark.xfail(strict=True, reason="4.7c rework: C1")
def test_views_and_frame_keys_both_count_as_frame_collection():
    """lag 1: коллекция с ``_shm_views`` (без ключа frame), сигнал, коллекция с ``frame``.
    Укладка третьей: кадровых уже 1 >= потолка -> выброшена ПЕРВАЯ (view-коллекция v1) — значит, ``_shm_views``
    распознан как кадр; сигнал между ними на месте. Итог [sig, f2], выброшено 1.

    Если бы view-коллекция кадром не считалась — v1 осталась бы (кадровых 0), в очереди [v1, sig, f2]."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=1)

    for coll in (_views("v1"), _signal("sig"), _frame("f2")):
        receiver.on_items_ready(coll)

    assert _drain(chain) == ["sig", "f2"]
    assert receiver.lag_dropped_total == 1


@pytest.mark.xfail(strict=True, reason="4.7c rework: C1 (join: сигнал внутри коллекции с кадром = кадровая)")
def test_join_collection_with_signal_part_counts_as_frame():
    """Коллекция join [сигнал-часть, кадр-часть] — КАДРОВАЯ (хотя бы один item несёт кадр) и потолком
    выбрасывается как кадровая. lag 1: j1 (join), чистый сигнал sig, j2 (join) -> выброшена j1, сигнал жив:
    [sig, j2], выброшено 1. Если бы смешанная коллекция кадровой не считалась, j1 осталась бы."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=1)

    def join(marker: str) -> list[dict]:
        return [{"marker": marker, "command": "draw"}, {"marker": marker + "_pix", "frame": np.zeros((2, 2), np.uint8)}]

    for coll in (join("j1"), _signal("sig"), join("j2")):
        receiver.on_items_ready(coll)

    assert _drain(chain) == ["sig", "j2"]
    assert receiver.lag_dropped_total == 1


# =============================================================================
# C3. Глубина IPC-очереди измеряется: gauge + transit_over_budget
# =============================================================================


def _run_receiver_with_depths(depths: list[int], *, budget: int, lag: int, tail_depth: int = 0) -> DataReceiver:
    """Настоящий ``run_loop`` в daemon-потоке: на первые ``len(depths)`` получений приходят сообщения
    (i-е показание ``ipc_depth_fn`` — ``depths[i]``), дальше сообщений нет, глубина ``tail_depth``. Ждём, пока
    все сообщения разобраны, и останавливаем воркер с дедлайном join."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    msgs = [{"type": "data", "data": {"marker": f"m{i}", "command": "draw"}} for i in range(len(depths))]
    lock = threading.Lock()
    state = {"recv": 0, "depth_calls": 0}

    def receive(**_):
        with lock:
            i = state["recv"]
            state["recv"] += 1
        return msgs[i] if i < len(msgs) else None

    def ipc_depth() -> int:
        # i-й вызов -> i-е показание, независимо от того, читает приёмник глубину до или после receive():
        # сообщения идут первыми len(depths) получениями, холостые получения дальше видят tail_depth.
        with lock:
            i = state["depth_calls"]
            state["depth_calls"] += 1
        return depths[i] if i < len(depths) else tail_depth

    collector = PassThroughCollector()
    receiver = DataReceiver(
        receive_fn=receive,
        shm_middleware=None,
        item_collector=collector,
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        max_lag_items=lag,
        inflight_budget=budget,
        ipc_depth_fn=ipc_depth,
    )
    collector._on_ready = receiver.on_items_ready

    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=receiver.run_loop, args=(stop, pause), daemon=True)
    worker.start()
    # Цикл последовательный: получение номер len(msgs) (холостое) начинается только после того, как
    # все сообщения разобраны. Размер chain_queue не смотрим: потолок отставания вправе его резать.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        with lock:
            if state["recv"] > len(msgs):
                break
        time.sleep(0.01)
    time.sleep(0.1)  # дать холостому получению закончить учёт глубины
    stop.set()
    worker.join(5.0)
    assert not worker.is_alive(), "run_loop не завершился за 5 с"
    assert state["recv"] > len(msgs), f"стенд неисправен: приёмник сделал {state['recv']} получений из {len(msgs)}"
    return receiver


@pytest.mark.xfail(strict=True, reason="4.7c rework: C3")
def test_transit_over_budget_counted_on_both_sides_of_the_boundary():
    """B = 6, lag 2 -> порог транзита B - lag = 4. Глубина IPC на получениях: 0, 4, 5, 7, 4 -> считаются
    ровно две (5 и 7: строго больше 4); глубина ровно 4 не считается ни разу (граница с обеих сторон)."""
    receiver = _run_receiver_with_depths([0, 4, 5, 7, 4], budget=6, lag=2)

    assert receiver.transit_over_budget == 2


@pytest.mark.xfail(strict=True, reason="4.7c rework: C3 (gauge глубины IPC-очереди)")
def test_ipc_depth_gauge_is_recorded():
    """Каждое получение пишет глубину IPC-очереди gauge'ом: постоянная глубина 13 (число, которого нет
    среди остальных метрик цикла) видна наружу — свойством ``ipc_queue_depth`` или полем
    ``get_cycle_metrics()`` с «depth» в имени (адрес gauge'а брифом не задан, см. докстринг модуля)."""
    receiver = _run_receiver_with_depths([13, 13, 13], budget=6, lag=2, tail_depth=13)

    metrics = receiver.get_cycle_metrics()
    seen = [getattr(receiver, "ipc_queue_depth", None)] + [v for k, v in metrics.items() if "depth" in k.lower()]
    assert 13 in seen, f"gauge глубины 13 не найден: {seen}; ключи метрик цикла {sorted(metrics)}"
