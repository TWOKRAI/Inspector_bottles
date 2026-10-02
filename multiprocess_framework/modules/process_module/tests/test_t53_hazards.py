# -*- coding: utf-8 -*-
"""Task 5.3 — авторские hazard-тесты записи о разрыве (teamlead, автор реализации).

Что может сломаться именно в ЭТОМ механизме, учитывая, как он построен:
  * слияние в хвост дописывает ``pending[-1]`` в ``chain_queue``. Без ``chain.mutex`` исполнитель может снять
    эту коллекцию ``get()`` между проверкой хвоста и ``extend`` — дописанные маркеры уедут в уже отработанный
    список и пропадут молча (Σ count на выходе меньше входа, счётчиков потери нет);
  * чанк ``GAP_CHUNK`` режет поток на несколько записей: порядок ``trace_ids`` обязан сохраниться ПОПЕРЁК записей
    и поперёк целей fan-out (запись i уходит всем целям раньше записи i+1);
  * формула ADR-174 п. 5 в items: узел получает смесь — записи соседа (``count`` > 1), маркеры, маркеры без ключа
    ``count`` (до 5.3) и кадры, которые его собственный потолок заменяет маркерами. ``handled − own`` обязан равняться
    Σ count чужих потерь, даже когда приёмник склеивает своё и чужое в одну коллекцию, а исполнитель — в одну запись.

Всё, что может заблокироваться, идёт в daemon-потоке с дедлайном на ``join``.
"""

from __future__ import annotations

import collections
import queue
import threading
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver, _MarkerBatch
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker, is_marker

DEADLINE_S = 15.0


def _bounded(fn: Callable[[], Any], deadline: float = DEADLINE_S) -> Any:
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


class _NullCollector:
    def on_item(self, item: dict) -> None:  # pragma: no cover — в этих тестах кадры идут через _Passthrough
        raise AssertionError("коллектор не должен вызываться")

    def check_timeouts(self) -> None:
        return None

    def pending_count(self) -> int:
        return 0


class _Passthrough:
    """Одиночный join: item сразу коллекцией в приёмник."""

    def __init__(self) -> None:
        self.receiver: DataReceiver | None = None

    def on_item(self, item: dict) -> None:
        assert self.receiver is not None
        self.receiver.on_items_ready([item])

    def check_timeouts(self) -> None:
        return None

    def pending_count(self) -> int:
        return 0


def _marker(tid: str, *, reason: str = "lag", ts: float = 1.0) -> dict:
    return build_marker({"trace_id": tid, "capture_ts": ts, "camera_id": "cam0"}, reason=reason, source="up")


def _record(prefix: str, n: int, *, ts0: float = 0.0) -> dict:
    """Запись соседа литералом (не через build_gap): вход «пришла по IPC»."""
    return {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "count": n,
        "trace_ids": [f"{prefix}{i}" for i in range(n)],
        "first_capture_ts": ts0,
        "last_capture_ts": ts0 + n - 1,
        "reasons": {"lag": n},
        "sources": {"up": n},
        "source": "up",
        "camera_id": "cam0",
    }


def _ids(item: dict) -> list:
    return list(item["trace_ids"]) if "trace_ids" in item else [item.get("trace_id", "")]


# =============================================================================================
# 1. Слияние в хвост против get() исполнителя: замок держит обе операции
# =============================================================================================
class _HookedDeque(collections.deque):
    """deque очереди, у которой чтение хвоста (``pending[-1]``) зовёт хук — момент «между проверкой и extend»."""

    hook: Callable[[], None] | None = None

    def __getitem__(self, index):  # type: ignore[override]
        if index == -1 and self.hook is not None:
            hook, self.hook = self.hook, None
            hook()
        return super().__getitem__(index)


def test_tail_merge_holds_chain_mutex_against_executor_get():
    """Внутри слияния (на чтении хвоста) стартует ``get()`` исполнителя. Под замком ``get`` НЕ завершается, пока
    слияние не дописало хвост; после — он забирает ОДНУ коллекцию из обоих маркеров, очередь пуста, потерь нет.

    Без замка ``get`` снимает голову за микросекунды внутри окна 0.3 с, ``extend`` идёт в уже снятый список,
    и проверка ``got_inside_merge`` краснеет. Окно 0.3 с — запас против планировщика: ложный зелёный под поломкой
    возможен, только если поток ``get`` не получил квант 0.3 с подряд.
    """
    chain: queue.Queue = queue.Queue(maxsize=8)
    receiver = DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=None,
        item_collector=_NullCollector(),
        chain_queue=chain,
        node_name="n",
        overflow="every",
    )
    hooked = _HookedDeque()
    chain.queue = hooked
    first = _MarkerBatch([_marker("a")])
    _bounded(lambda: receiver.on_items_ready(first))
    assert chain.qsize() == 1, "стенд неисправен: первая маркер-коллекция не легла в очередь"

    taken: list = []
    got = threading.Event()
    state: dict = {}

    def executor_get() -> None:
        taken.append(chain.get(timeout=DEADLINE_S))
        got.set()

    getter = threading.Thread(target=executor_get, daemon=True)

    def inside_merge() -> None:
        getter.start()
        state["got_inside_merge"] = got.wait(0.3)

    hooked.hook = inside_merge
    _bounded(lambda: receiver.on_items_ready(_MarkerBatch([_marker("b")])))
    getter.join(DEADLINE_S)

    assert not getter.is_alive(), "get() исполнителя завис"
    assert state == {"got_inside_merge": False}, "get() исполнителя прошёл внутри слияния — замок не держится"
    assert [[m["trace_id"] for m in coll] for coll in taken] == [["a", "b"]]
    assert chain.qsize() == 0


# =============================================================================================
# 2. Порядок trace_ids поперёк чанков и целей
# =============================================================================================
def _executor(*, targets=("t1", "t2"), overflow="every") -> tuple[PipelineExecutor, list]:
    sent: list = []
    ex = PipelineExecutor(
        plugins=[],
        chain_targets=list(targets),
        shm_middleware=None,
        send_fn=lambda target, msg: sent.append((target, msg)),
        node_name="ex",
        overflow=overflow,
    )
    return ex, sent


def test_trace_ids_order_survives_chunking_across_records_and_targets():
    """Вход: 1000 маркеров, запись соседа на 800, 1000 маркеров, запись на 1500, 3 маркера (Σ 4303).
    Жадная упаковка неделимых входов: 1000 маркеров; запись 800 не влезает (1800) → новая, её добивают 700
    маркеров n0..n699 до 1500; n700..n999 = 300; запись 1500 не влезает → новая; 3 маркера → новая. Ожидаемые
    длины записей — литерал: 1000, 1500, 300, 1500, 3. Склейка ``trace_ids`` по записям = порядок входа;
    каждая запись уходит обеим целям подряд (t1, t2), запись i+1 — после записи i; handled = 4303."""
    batch = _MarkerBatch(
        [_marker(f"m{i}") for i in range(1000)]
        + [_record("r", 800)]
        + [_marker(f"n{i}") for i in range(1000)]
        + [_record("s", 1500)]
        + [_marker(f"z{i}") for i in range(3)]
    )
    expected_ids = [t for it in batch for t in _ids(it)]
    ex, sent = _executor()

    _bounded(lambda: ex._run_batch(batch, 0.0))

    assert [t for t, _m in sent] == ["t1", "t2"] * 5
    counts = [m["data"]["count"] for _t, m in sent]
    assert counts == [1000, 1000, 1500, 1500, 300, 300, 1500, 1500, 3, 3]
    per_record = [m["data"] for t, m in sent if t == "t1"]
    assert [t for d in per_record for t in d["trace_ids"]] == expected_ids
    assert all(len(d["trace_ids"]) == d["count"] for d in per_record)
    assert ex.get_cycle_metrics()["not_inspected_handled"] == 4303


# =============================================================================================
# 3. Формула ADR-174 п. 5 в items на смеси записей, маркеров и своих потерь
# =============================================================================================
def _frame_msg(tid: str) -> dict:
    data = {"frame": np.zeros((2, 2), dtype=np.uint8), "trace_id": tid, "capture_ts": 1.0, "camera_id": "cam0"}
    return {"data": data, "sender": "up", "type": "data", "channel": "data"}


def _gap_msg(item: dict) -> dict:
    return {"data": dict(item), "sender": "up", "type": "data", "channel": "data"}


def _legacy_marker(tid: str) -> dict:
    """Маркер соседа до 5.3: без ключа ``count``."""
    m = _marker(tid)
    del m["count"]
    return m


class _Feed:
    def __init__(self, messages: list[dict]) -> None:
        self.pending = list(messages)
        self.drained = threading.Event()

    def __call__(self, **_kwargs: Any) -> dict | None:
        if self.pending:
            return self.pending.pop(0)
        self.drained.set()
        return None


def test_adr174_formula_in_items_with_mixed_records_markers_and_own_lag():
    """Узел ``every``, потолок 1, исполнитель стоит, пока приёмник не дочитал. Вход (по порядку): f0, rec(5),
    f1, m1 (count 1), f2, rec(1500), f3, legacy (без count), f4, rec(7), f5. Чужие потери Σ = 5+1+1500+1+7 = 1514
    (литерал). Свои: потолок 1 из 6 кадров заменяет 5 (f0..f4) — литерал. Ожидание: ``handled − own == 1514``,
    Σ count отправленных записей = handled = 1519, ни одна запись не больше 1500, ``trace_ids`` = порядок входа
    без f5 (он доехал кадром), дублей нет."""
    rec5, rec1500, rec7 = _record("a", 5), _record("b", 1500), _record("c", 7)
    inputs = [
        _frame_msg("f0"),
        _gap_msg(rec5),
        _frame_msg("f1"),
        _gap_msg(_marker("m1")),
        _frame_msg("f2"),
        _gap_msg(rec1500),
        _frame_msg("f3"),
        _gap_msg(_legacy_marker("L1")),
        _frame_msg("f4"),
        _gap_msg(rec7),
        _frame_msg("f5"),
    ]
    chain: queue.Queue = queue.Queue(maxsize=64)
    feed = _Feed(inputs)
    passthrough = _Passthrough()
    rcv = DataReceiver(
        receive_fn=feed,
        shm_middleware=None,
        item_collector=passthrough,
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        node_name="node",
        max_lag_items=1,
        overflow="every",
    )
    passthrough.receiver = rcv
    ex, sent = _executor(targets=("next",))
    ex.bind_queue(chain)
    e_stop, e_pause = threading.Event(), threading.Event()
    e_pause.set()
    e_worker = threading.Thread(target=ex.run, args=(e_stop, e_pause), daemon=True)
    e_worker.start()
    r_stop, r_pause = threading.Event(), threading.Event()
    r_worker = threading.Thread(target=rcv.run_loop, args=(r_stop, r_pause), daemon=True)
    r_worker.start()
    try:
        assert feed.drained.wait(DEADLINE_S), "приёмник не дочитал вход"
        r_stop.set()
        r_worker.join(DEADLINE_S)
        assert not r_worker.is_alive(), "run_loop приёмника завис"
        e_pause.clear()
        waiter = threading.Event()
        for _ in range(int(DEADLINE_S / 0.01)):
            if chain.empty():
                break
            waiter.wait(0.01)
    finally:
        r_stop.set()
        e_stop.set()
        e_worker.join(DEADLINE_S)
    assert not e_worker.is_alive(), "исполнитель завис"

    own = rcv.get_cycle_metrics()["not_inspected_lag"]
    handled = ex.get_cycle_metrics()["not_inspected_handled"]
    gaps = [m["data"] for _t, m in sent if is_marker(m["data"])]
    frames = [m["data"]["trace_id"] for _t, m in sent if not is_marker(m["data"])]

    assert own == 5, f"стенд: свой потолок заменил {own} кадров, ждали 5"
    assert frames == ["f5"]
    assert handled - own == 1514
    assert sum(g["count"] for g in gaps) == handled == 1519
    assert all(g["count"] <= 1500 for g in gaps)
    expected = (
        ["f0"] + rec5["trace_ids"] + ["f1", "m1", "f2"] + rec1500["trace_ids"] + ["f3", "L1", "f4"] + rec7["trace_ids"]
    )
    got = [t for g in gaps for t in g["trace_ids"]]
    assert got == expected
    assert len(set(got)) == len(got)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
