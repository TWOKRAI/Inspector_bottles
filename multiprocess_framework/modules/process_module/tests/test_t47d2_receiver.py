# -*- coding: utf-8 -*-
"""Task 4.7d-2 — слепые приёмочные тесты ``DataReceiver``: рождение маркера ``not_inspected``.

Независимый tester, от acceptance 4.7d-2 (plans/transport-single-policy/task-4.7.md), без чтения
реализации 4.7d-2 (её в дереве нет). Все ожидаемые значения — литералы из acceptance.

Что пинится (приёмник):
  * ``_bound_lag`` под ``overflow="every"``: выброшенная кадровая коллекция заменяется НА ТОМ ЖЕ МЕСТЕ
    очереди коллекцией маркеров ``reason="lag"``; соседние маркер-коллекции склеиваются (в том числе при
    ``excess > 1``); сигнальная коллекция не трогается; ``put`` не блокируется;
  * счётчики ``lag_dropped_items`` (оба режима) / ``not_inspected_lag`` (только ``every``);
  * restore: отказ ``restore_frame`` (метка ``_shm_dropped``) под ``every`` рождает маркер
    ``stale_restore`` мимо коллектора; под ``latest`` — ничего;
  * пришедший по IPC маркер идёт мимо коллектора отдельной коллекцией в обоих режимах;
  * ``overflow`` вне ("latest", "every") -> ``ValueError``.

Зелёные контроли (держат стенд честным, зелёные и до, и после реализации): restore под ``latest``.
Всё, что может заблокироваться (``on_items_ready`` на заполненной очереди, ``run_loop``), гоняется в
daemon-потоке с дедлайном на ``join``.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker, is_marker
from multiprocess_framework.modules.router_module.tests import test_frame_ref_gen as _T

DEADLINE_S = 10.0
NODE = "recv_node"


# --------------------------------------------------------------------------------------------
# стенд
# --------------------------------------------------------------------------------------------
@pytest.fixture
def rig(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)
    r = _T._Rig()
    yield r
    r.close()


def _bounded(fn: Callable[[], Any], seconds: float = DEADLINE_S) -> Any:
    """``fn`` в daemon-потоке с дедлайном: зависание = FAIL, а не висящий прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в основной поток
            box["error"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        pytest.fail(f"вызов завис (> {seconds} с) — блокирующий put приёмника")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class _SpyCollector:
    """Коллектор-шпион: ``on_item`` только запоминает item (в chain_queue сам не кладёт)."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def on_item(self, item: dict) -> None:
        self.items.append(item)

    def check_timeouts(self) -> None:
        return None

    def pending_count(self) -> int:
        return 0


def _receiver(chain: queue.Queue, *, lag: int = 0, overflow: str = "latest", shm=None, collector=None, receive_fn=None):
    return DataReceiver(
        receive_fn=receive_fn or (lambda **_: None),
        shm_middleware=shm,
        item_collector=collector if collector is not None else _SpyCollector(),
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        node_name=NODE,
        max_lag_items=lag,
        overflow=overflow,
    )


def _frame(trace_id: str, capture_ts: float | None = None, **extra) -> list[dict]:
    """Кадровая коллекция из ОДНОГО item'а: настоящий ndarray в ``frame``."""
    item: dict[str, Any] = {"frame": np.zeros((2, 2), dtype=np.uint8), "trace_id": trace_id}
    if capture_ts is not None:
        item["capture_ts"] = capture_ts
    item.update(extra)
    return [item]


def _signal(tag: str) -> list[dict]:
    """Сигнальная коллекция: ни ``frame``, ни ``_shm_views``."""
    return [{"tag": tag, "command": "draw"}]


def _shape(chain: queue.Queue) -> list[tuple[str, list[str]]]:
    """Содержимое очереди по порядку без её изменения: ('M', [trace_id...]) для коллекции маркеров,
    ('C', [trace_id...]) для прочих (сигнальные несут ``tag`` вместо trace_id)."""
    with chain.mutex:
        colls = [list(c) for c in chain.queue]
    out: list[tuple[str, list[str]]] = []
    for coll in colls:
        kind = "M" if coll and all(is_marker(it) for it in coll) else "C"
        out.append((kind, [it.get("trace_id") or it.get("tag") for it in coll]))
    return out


def _markers(chain: queue.Queue) -> list[dict]:
    with chain.mutex:
        return [it for c in chain.queue for it in c if is_marker(it)]


def _feed_all(receiver: DataReceiver, colls: list[list[dict]]) -> None:
    for coll in colls:
        receiver.on_items_ready(coll)


# --------------------------------------------------------------------------------------------
# _bound_lag под every / latest
# --------------------------------------------------------------------------------------------
def test_bound_every_lag2_replaces_in_place_and_glues_markers_into_one_collection():
    """Bound, every, lag 2, maxsize 64, исполнитель не читает; кадры по 1 item t1..t6 -> после шестой
    qsize 3, порядок [M(t1,t2,t3,t4), c5, c6], маркеры reason=lag в порядке trace_id;
    lag_dropped_total == 4, lag_dropped_items == 4, not_inspected_lag == 4."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=2, overflow="every")

    _bounded(lambda: _feed_all(receiver, [_frame(f"t{i}", float(i)) for i in range(1, 7)]))

    assert chain.qsize() == 3
    assert _shape(chain) == [("M", ["t1", "t2", "t3", "t4"]), ("C", ["t5"]), ("C", ["t6"])]
    markers = _markers(chain)
    assert [m["reason"] for m in markers] == ["lag"] * 4
    assert [m["source"] for m in markers] == [NODE] * 4
    assert [m["capture_ts"] for m in markers] == [1.0, 2.0, 3.0, 4.0]
    assert all("frame" not in m for m in markers)
    metrics = receiver.get_cycle_metrics()
    assert receiver.lag_dropped_total == 4
    assert metrics["lag_dropped_items"] == 4
    assert metrics["not_inspected_lag"] == 4


def test_bound_every_small_queue_50_collections_never_blocks():
    """Bound, every, lag 2, chain_queue maxsize=3, 50 кадровых коллекций подряд, исполнитель не читает:
    приёмник не блокируется (вызов завершается до дедлайна), qsize <= 3, not_inspected_lag == 48."""
    chain: queue.Queue = queue.Queue(maxsize=3)
    receiver = _receiver(chain, lag=2, overflow="every")

    _bounded(lambda: _feed_all(receiver, [_frame(f"t{i}") for i in range(1, 51)]))

    assert chain.qsize() <= 3
    assert receiver.get_cycle_metrics()["not_inspected_lag"] == 48


def test_bound_every_excess_3_yields_one_marker_collection():
    """every, lag 2: очередь заполнена НАПРЯМУЮ (мимо приёмника) кадрами [b1,b2,b3,b4], затем через
    приёмник приходит b5 (excess == 3). Очередь [M(b1,b2,b3), b4, b5]: маркеры ОДНОЙ коллекцией,
    соседних маркер-коллекций нет; not_inspected_lag == 3."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    for tid in ("b1", "b2", "b3", "b4"):
        chain.put(_frame(tid))
    receiver = _receiver(chain, lag=2, overflow="every")

    _bounded(lambda: receiver.on_items_ready(_frame("b5")))

    assert _shape(chain) == [("M", ["b1", "b2", "b3"]), ("C", ["b4"]), ("C", ["b5"])]
    assert receiver.get_cycle_metrics()["not_inspected_lag"] == 3


def test_bound_latest_same_input_deletes_without_markers():
    """Тот же вход t1..t6 при latest: qsize 2, [c5, c6], маркеров 0; lag_dropped_total == 4,
    lag_dropped_items == 4, ключа not_inspected_lag в get_cycle_metrics() нет."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=2, overflow="latest")

    _bounded(lambda: _feed_all(receiver, [_frame(f"t{i}") for i in range(1, 7)]))

    assert chain.qsize() == 2
    assert _shape(chain) == [("C", ["t5"]), ("C", ["t6"])]
    assert _markers(chain) == []
    metrics = receiver.get_cycle_metrics()
    assert receiver.lag_dropped_total == 4
    assert metrics["lag_dropped_items"] == 4
    assert "not_inspected_lag" not in metrics


def test_bound_every_two_item_collection_becomes_two_markers_in_its_place():
    """Выброшена коллекция из 2 items (t1, t2) при every: на её месте ОДНА коллекция из 2 маркеров
    (t1, t2); lag_dropped_total +1, lag_dropped_items +2, not_inspected_lag +2."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=1, overflow="every")
    two = _frame("t1") + _frame("t2")

    def scenario() -> None:
        receiver.on_items_ready(two)
        receiver.on_items_ready(_frame("t3"))

    _bounded(scenario)

    assert _shape(chain) == [("M", ["t1", "t2"]), ("C", ["t3"])]
    metrics = receiver.get_cycle_metrics()
    assert receiver.lag_dropped_total == 1
    assert metrics["lag_dropped_items"] == 2
    assert metrics["not_inspected_lag"] == 2


def test_bound_signal_collection_is_never_replaced_and_separates_markers():
    """Сигнальная коллекция (без frame и _shm_views) не заменяется маркером, не вытесняется и разделяет
    маркеры. Очередь [сигнал, c1, c2], приходит c3, lag 2 -> [сигнал, M(c1), c2, c3]; затем c4 ->
    [сигнал, M(c1,c2), c3, c4]."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=2, overflow="every")

    _bounded(lambda: _feed_all(receiver, [_signal("sig"), _frame("c1"), _frame("c2")]))
    assert _shape(chain) == [("C", ["sig"]), ("C", ["c1"]), ("C", ["c2"])]

    _bounded(lambda: receiver.on_items_ready(_frame("c3")))
    assert _shape(chain) == [("C", ["sig"]), ("M", ["c1"]), ("C", ["c2"]), ("C", ["c3"])]

    _bounded(lambda: receiver.on_items_ready(_frame("c4")))
    assert _shape(chain) == [("C", ["sig"]), ("M", ["c1", "c2"]), ("C", ["c3"]), ("C", ["c4"])]


def test_bound_every_join_collection_yields_one_marker_without_pult():
    """Join: выброшена коллекция [{"frame": f, "trace_id": "t1", "pult": {...}}] -> ровно 1 маркер t1; в
    маркере нет ключа pult; lag_dropped_items == 1."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=1, overflow="every")
    joined = [{"frame": np.zeros((2, 2), dtype=np.uint8), "trace_id": "t1", "pult": {"knob": 3}}]

    def scenario() -> None:
        receiver.on_items_ready(joined)
        receiver.on_items_ready(_frame("t2"))

    _bounded(scenario)

    markers = _markers(chain)
    assert [m["trace_id"] for m in markers] == ["t1"]
    assert "pult" not in markers[0]
    assert receiver.get_cycle_metrics()["lag_dropped_items"] == 1


# --------------------------------------------------------------------------------------------
# run_loop: restore и IPC-маркер
# --------------------------------------------------------------------------------------------
def _run_loop_once(
    receiver_factory: Callable[[Callable[..., Any]], DataReceiver], messages: list[dict]
) -> DataReceiver:
    """Прогнать ``run_loop`` по списку сообщений и остановить его, когда приёмник вернулся за
    следующим сообщением (значит предыдущее обработано целиком, включая on_items_ready).
    ``receiver_factory(receive_fn)`` строит приёмник вокруг переданного ``receive_fn``."""
    pending = list(messages)
    drained = threading.Event()

    def receive_fn(**_kwargs: Any) -> dict | None:
        if pending:
            return pending.pop(0)
        drained.set()
        return None

    receiver = receiver_factory(receive_fn)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=receiver.run_loop, args=(stop, pause), daemon=True)
    worker.start()
    ok = drained.wait(DEADLINE_S)
    stop.set()
    worker.join(DEADLINE_S)
    if not ok:
        pytest.fail("приёмник не дочитал сообщения за дедлайн")
    if worker.is_alive():
        pytest.fail("run_loop не завершился после stop_event")
    return receiver


class _DroppingShm:
    """restore_frame, который ВСЕГДА отказывает: ставит метку ``_shm_dropped`` на data (как настоящий)."""

    def restore_frame(self, msg: dict) -> dict:
        msg["data"]["_shm_dropped"] = True
        return msg


def _lost_msg() -> dict:
    return {"data": {"trace_id": "t9", "capture_ts": 3.5, "frame_id": 4}}


def test_restore_every_dropped_message_becomes_marker_bypassing_collector():
    """Restore, every: restore_frame вернул msg с _shm_dropped (trace_id t9, capture_ts 3.5). В chain_queue
    одна коллекция из одного маркера {reason: stale_restore, trace_id: t9, capture_ts: 3.5, source: имя
    узла}; collector.on_item не вызывался; not_inspected_stale_restore == 1."""
    chain: queue.Queue = queue.Queue(maxsize=8)
    collector = _SpyCollector()
    receiver = _run_loop_once(
        lambda rf: _receiver(chain, overflow="every", shm=_DroppingShm(), collector=collector, receive_fn=rf),
        [_lost_msg()],
    )

    assert collector.items == []
    assert chain.qsize() == 1
    coll = chain.get_nowait()
    assert len(coll) == 1
    marker = coll[0]
    assert is_marker(marker)
    assert (marker["reason"], marker["trace_id"], marker["capture_ts"], marker["source"]) == (
        "stale_restore",
        "t9",
        3.5,
        NODE,
    )
    assert receiver.get_cycle_metrics()["not_inspected_stale_restore"] == 1


def test_restore_latest_dropped_message_is_silently_skipped_control():
    """CONTROL (зелёный и до реализации): при latest отказ restore -> chain_queue пуст, коллектор не
    вызывался, ключа not_inspected_stale_restore в метриках нет."""
    chain: queue.Queue = queue.Queue(maxsize=8)
    collector = _SpyCollector()
    receiver = _run_loop_once(
        lambda rf: _receiver(chain, overflow="latest", shm=_DroppingShm(), collector=collector, receive_fn=rf),
        [_lost_msg()],
    )

    assert chain.qsize() == 0
    assert collector.items == []
    assert "not_inspected_stale_restore" not in receiver.get_cycle_metrics()


def _make_failure(kind: str, writer, wire: dict) -> None:
    """Довести провод-сообщение до одного из четырёх отказов restore (по ссылке ``frame``)."""
    ref = wire["data"]["_shm_refs"]["frame"]
    if kind == "overwritten_before_read":
        _T._overwrite(writer, "frame")
    elif kind == "torn":
        from multiprocess_framework.modules.shared_resources_module.memory.format import buffer as buf_mod

        handle = writer._mm.get_memory_data("A", ref["slot"])["handles"][ref["idx"]]
        odd = buf_mod.read_generation(handle.buf) + 1
        buf_mod._write_generation(handle.buf, odd)  # писатель «в процессе записи»: нечётное поколение
        ref["gen"] = odd
    elif kind == "unlinked_segment":
        ref["name"] = "no_such_segment_4_7d2"
    elif kind == "broken_ref":
        ref["name"] = None
    else:  # pragma: no cover - опечатка в параметризации
        raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["overwritten_before_read", "torn", "unlinked_segment", "broken_ref"])
def test_restore_every_real_middleware_each_failure_gives_exactly_one_marker(rig, kind):
    """Restore на реальном middleware, every, четыре отказа по одному (перезапись слота до чтения;
    перезапись во время чтения; отвязанный сегмент; битая ссылка): каждый даёт ровно 1 маркер
    stale_restore, и после каждого Δframe_stale_drops + Δframe_torn_reads + Δframe_restore_failures == 1."""
    writer, reader = rig.make("A"), rig.make("B")
    wire = _T._wire(_T._send(writer, {"frame": _T._arr("frame", 1), "trace_id": "t9", "capture_ts": 3.5}))
    _make_failure(kind, writer, wire)
    before = (reader.frame_stale_drops, reader.frame_torn_reads, reader.frame_restore_failures)
    chain: queue.Queue = queue.Queue(maxsize=8)
    collector = _SpyCollector()

    _run_loop_once(
        lambda rf: _receiver(chain, overflow="every", shm=reader, collector=collector, receive_fn=rf), [wire]
    )

    after = (reader.frame_stale_drops, reader.frame_torn_reads, reader.frame_restore_failures)
    assert sum(after) - sum(before) == 1, f"{kind}: счётчики до {before}, после {after}"
    assert collector.items == []
    assert chain.qsize() == 1
    coll = chain.get_nowait()
    assert len(coll) == 1 and is_marker(coll[0])
    assert (coll[0]["reason"], coll[0]["trace_id"], coll[0]["capture_ts"]) == ("stale_restore", "t9", 3.5)


@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_ipc_marker_bypasses_collector_in_its_own_collection(overflow):
    """Пришедший по IPC маркер (is_marker), latest и every: collector.on_item не вызывался, в chain_queue
    отдельная коллекция из этого item'а, все поля маркера целы (допустим добавленный ключ sender),
    source не изменён."""
    marker = build_marker(
        {"trace_id": "t7", "capture_ts": 9.25, "frame_id": 12, "camera_id": "cam0"},
        reason="lag",
        source="upstream_proc",
    )
    chain: queue.Queue = queue.Queue(maxsize=8)
    collector = _SpyCollector()
    _run_loop_once(
        lambda rf: _receiver(chain, overflow=overflow, collector=collector, receive_fn=rf),
        [{"data": dict(marker), "sender": "upstream_proc", "type": "data", "channel": "data"}],
    )

    assert collector.items == []
    assert chain.qsize() == 1
    coll = chain.get_nowait()
    assert len(coll) == 1
    item = coll[0]
    assert is_marker(item)
    for key, value in marker.items():
        assert item[key] == value, f"поле маркера {key!r} изменено: {item[key]!r} != {value!r}"
    assert item["source"] == "upstream_proc"
    assert set(item) - set(marker) <= {"sender"}


# --------------------------------------------------------------------------------------------
# конструктор
# --------------------------------------------------------------------------------------------
def test_receiver_rejects_unknown_overflow():
    """DataReceiver(..., overflow="Every") -> ValueError (регистр значения важен)."""
    with pytest.raises(ValueError):
        DataReceiver(
            receive_fn=lambda **_: None,
            shm_middleware=None,
            item_collector=_SpyCollector(),
            chain_queue=queue.Queue(),
            overflow="Every",
        )
