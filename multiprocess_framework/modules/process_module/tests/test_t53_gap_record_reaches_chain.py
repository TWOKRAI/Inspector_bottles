# -*- coding: utf-8 -*-
"""Task 5.3 — слепые приёмочные тесты: запись о разрыве от соседа доходит до цепочки узла целой.

Независимый tester, от acceptance Task 5.3 (plans/transport-single-policy/phase-5.md, «### Task 5.3»),
без чтения реализации 5.3 (её в дереве нет). Ожидаемые значения — литералы.

Что пинится (узел-получатель, ``DataReceiver`` -> ``chain_queue`` -> ``PipelineExecutor``):
  * IPC-запись ``count=1078`` (``is_marker`` истинен) идёт отдельной коллекцией ``_MarkerBatch`` мимо коллектора,
    в обоих режимах; поля ``count``, ``trace_ids``, ``first_capture_ts``, ``last_capture_ts``, ``reasons``, ``sources``
    дошли без изменений;
  * spy-плагин с ``accepts_markers = True`` вызван ровно 1 раз, ``data`` целиком цел; плагин без ``accepts_markers``
    не вызван, ``send_fn`` получает запись как есть;
  * ``not_inspected_handled`` исполнителя растёт на ``count`` записи (1078), а не на 1.

Зелёные контроли (зелёные и до реализации: сегодня запись — обычный маркер с лишними ключами): приём отдельной
коллекцией, целость полей, 1 вызов плагина, проход мимо плагина без ``accepts_markers``. Красный до реализации —
только ``handled`` (``AssertionError``: 1 вместо 1078). Контроли нужны, чтобы реализация, которая начнёт резать
чужие ключи записи или гнать её через коллектор, упала здесь.

Всё, что может заблокироваться (``run_loop``, ``run``), гоняется в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver, _MarkerBatch
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor

DEADLINE_S = 15.0
SERVICE_KEYS = {"_t_sent_ns", "_t_send", "_from"}
NODE = "neighbour"
N = 1078

RECORD = {
    "inspection_status": "not_inspected",
    "overflow_marker": True,
    "count": N,
    "trace_ids": [f"t{i}" for i in range(N)],
    "first_capture_ts": 1000.0,
    "last_capture_ts": 1000.0 + (N - 1),
    "reasons": {"lag": 1000, "stale_exec": 78},
    "sources": {"processor": N},
    "source": "processor",
    "camera_id": "cam0",
}


class _SpyCollector:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def on_item(self, item: dict) -> None:
        self.items.append(item)

    def check_timeouts(self) -> None:
        return None

    def pending_count(self) -> int:
        return 0


class _Plugin:
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self, name: str, *, accepts: bool | None = None) -> None:
        self.name = name
        if accepts is not None:
            self.accepts_markers = accepts
        self.calls = 0
        self.seen: list[list[dict]] = []

    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        self.seen.append(list(items))
        return items


def _ipc_msg() -> dict:
    # глубокая копия значений-списков не нужна: приёмник копирует верхний dict, а тест сверяет значения
    return {"data": dict(RECORD), "sender": "processor", "type": "data", "channel": "data"}


def _receive_one(overflow: str) -> tuple[queue.Queue, _SpyCollector]:
    """Один IPC-кадр-запись через настоящий ``DataReceiver.run_loop`` (daemon-поток, дедлайн)."""
    chain: queue.Queue = queue.Queue(maxsize=8)
    collector = _SpyCollector()
    pending = [_ipc_msg()]
    drained = threading.Event()

    def receive_fn(**_kwargs: Any) -> dict | None:
        if pending:
            return pending.pop(0)
        drained.set()
        return None

    receiver = DataReceiver(
        receive_fn=receive_fn,
        shm_middleware=None,
        item_collector=collector,
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        node_name=NODE,
        overflow=overflow,
    )
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=receiver.run_loop, args=(stop, pause), daemon=True)
    worker.start()
    ok = drained.wait(DEADLINE_S)
    stop.set()
    worker.join(DEADLINE_S)
    if not ok:
        pytest.fail("приёмник не дочитал сообщение за дедлайн")
    if worker.is_alive():
        pytest.fail("run_loop не завершился после stop_event")
    return chain, collector


def _execute(chain_item, plugins, *, overflow: str) -> tuple[PipelineExecutor, list]:
    """Отдать коллекцию из ``chain_queue`` настоящему исполнителю узла (``run``, daemon-поток, дедлайн)."""
    sent: list = []
    ex = PipelineExecutor(
        plugins=list(plugins),
        chain_targets=["next"],
        shm_middleware=None,
        send_fn=lambda target, msg: sent.append((target, msg)),
        node_name=NODE,
        overflow=overflow,
    )
    q: queue.Queue = queue.Queue()
    q.put(chain_item)
    ex.bind_queue(q)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
    worker.start()
    waiter = threading.Event()
    for _ in range(int(DEADLINE_S / 0.01)):
        if q.empty():
            break
        waiter.wait(0.01)
    else:
        stop.set()
        pytest.fail("исполнитель не выбрал очередь за дедлайн")
    stop.set()
    worker.join(DEADLINE_S)
    if worker.is_alive():
        pytest.fail("PipelineExecutor не завершил такт за дедлайн")
    return ex, sent


# --------------------------------------------------------------------------------------------
# приёмник
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_ipc_gap_record_goes_to_own_marker_collection_not_to_collector_control(overflow):
    """КОНТРОЛЬ (зелёный и до реализации)."""
    chain, collector = _receive_one(overflow)

    assert collector.items == []
    assert chain.qsize() == 1
    coll = chain.get_nowait()
    assert isinstance(coll, _MarkerBatch)
    assert len(coll) == 1


@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_ipc_gap_record_fields_arrive_unchanged_control(overflow):
    """КОНТРОЛЬ (зелёный и до реализации): шесть полей записи и остальные ключи целы; добавить можно только sender."""
    chain, _collector = _receive_one(overflow)

    (item,) = chain.get_nowait()

    for key in ("count", "trace_ids", "first_capture_ts", "last_capture_ts", "reasons", "sources"):
        assert item[key] == RECORD[key], f"поле записи {key!r} изменено приёмником"
    assert set(item) - set(RECORD) <= {"sender"}
    assert item["source"] == "processor"


# --------------------------------------------------------------------------------------------
# исполнитель узла-получателя
# --------------------------------------------------------------------------------------------
def test_accepting_plugin_is_called_exactly_once_with_the_intact_record_control():
    """КОНТРОЛЬ (зелёный и до реализации): spy ``accepts_markers=True`` вызван 1 раз, ``data`` цел."""
    chain, _collector = _receive_one("every")
    spy = _Plugin("keeper", accepts=True)

    _execute(chain.get_nowait(), [spy], overflow="every")

    assert spy.calls == 1
    assert len(spy.seen[0]) == 1
    item = spy.seen[0][0]
    for key, value in RECORD.items():
        assert item[key] == value, f"поле {key!r} изменено на пути до плагина"


def test_plain_plugin_is_skipped_and_record_is_forwarded_as_is_control():
    """КОНТРОЛЬ (зелёный и до реализации): плагин без ``accepts_markers`` не вызван, ``send_fn`` получает запись."""
    chain, _collector = _receive_one("every")
    plain = _Plugin("plain")

    _ex, sent = _execute(chain.get_nowait(), [plain], overflow="every")

    assert plain.calls == 0
    assert [t for t, _m in sent] == ["next"]
    data = {k: v for k, v in sent[0][1]["data"].items() if k not in SERVICE_KEYS and k != "sender"}
    assert data == RECORD


@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_handled_counts_the_record_count_not_one(overflow):
    chain, _collector = _receive_one(overflow)

    ex, _sent = _execute(chain.get_nowait(), [], overflow=overflow)

    assert ex.get_cycle_metrics()["not_inspected_handled"] == N
