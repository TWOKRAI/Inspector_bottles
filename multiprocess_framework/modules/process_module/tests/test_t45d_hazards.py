# -*- coding: utf-8 -*-
"""Task 4.5d — авторские hazard-тесты механизма ``transport_ms`` (внутренние ловушки).

Приёмочный контракт лежит в ``test_t45d_transport_ms.py`` (писал tester вслепую); здесь
только то, что видно автору, знающему устройство:

* fan-out: один item уходит нескольким targets — штамп ``_t_sent_ns`` ставится ОДИН раз
  до цикла по targets, и каждый получатель считает свой transport_ms. Ловушка: приёмник
  вынимает штамп из ``msg["data"]`` (pop). В межпроцессной доставке у получателя своя
  распакованная копия, поэтому pop одного не трогает соседа. Но В ПРОЦЕССЕ (без pickle)
  оба сообщения делят ОДИН dict ``item`` — там pop первого получателя лишил бы второго
  штампа; в проде такого пути нет (data-plane всегда через IPC-очередь), тест фиксирует это
  наблюдение, а не выдаёт его за гарантию.
* FW_FRAME_TRACE включён: ``_t_send`` (wall-время трассировки) и ``_t_sent_ns``
  (perf_counter_ns транспорта) живут рядом, не затирают друг друга, транспорт-спан
  трассировки по-прежнему появляется, а оба служебных поля снимаются до коллектора.
"""

from __future__ import annotations

import pickle
import queue
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic import frame_trace
from multiprocess_framework.modules.process_module.generic.collector_registry import PassThroughCollector
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor


def _send_through_executor(chain_targets: list[str], items: list[dict]) -> list[tuple[str, dict]]:
    """Прогнать items через настоящий PipelineExecutor.run; вернуть перехваченные (target, msg)."""
    sent: list[tuple[str, dict]] = []
    ex = PipelineExecutor(
        plugins=[],
        chain_targets=chain_targets,
        shm_middleware=None,
        send_fn=lambda t, m: sent.append((t, m)),
    )
    q: queue.Queue = queue.Queue()
    ex.bind_queue(q)
    q.put(items)
    stop, pause = threading.Event(), threading.Event()
    th = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
    th.start()
    deadline = time.monotonic() + 3.0
    while len(sent) < len(chain_targets) * len(items) and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    th.join(timeout=3.0)
    assert not th.is_alive(), "исполнитель не остановился за дедлайн (зависание)"
    return sent


def _deliver(msg: dict) -> tuple[dict, dict]:
    """Доставить msg приёмнику через pickle-круг (как IPC-очередь); вернуть (item, метрики)."""
    once = [pickle.loads(pickle.dumps(msg))]
    chain_q: queue.Queue = queue.Queue()
    dr = DataReceiver(
        receive_fn=lambda **kw: once.pop(0) if once else None,
        shm_middleware=None,
        item_collector=PassThroughCollector(),
        chain_queue=chain_q,
    )
    dr._collector._on_ready = dr.on_items_ready
    stop, pause = threading.Event(), threading.Event()
    th = threading.Thread(target=dr.run_loop, args=(stop, pause), daemon=True)
    th.start()
    deadline = time.monotonic() + 3.0
    while chain_q.empty() and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    th.join(timeout=3.0)
    assert not th.is_alive(), "приёмник не остановился за дедлайн (зависание)"
    return chain_q.get_nowait()[0], dr.get_cycle_metrics()


def test_t45d_fan_out_every_target_receiver_measures_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Один item → два targets: у обоих сообщений один и тот же int-штамп, и оба получателя
    (каждый со своей pickle-копией) дают transport_ms > 0 и item без штампа."""
    monkeypatch.delenv("FW_FRAME_TRACE", raising=False)
    sent = _send_through_executor(["a", "b"], [{"frame_id": 1}])
    assert [t for t, _ in sent] == ["a", "b"]

    stamps = [m["data"]["_t_sent_ns"] for _, m in sent]
    assert stamps[0] == stamps[1], "штамп ставится один раз на item, до цикла по targets"
    assert isinstance(stamps[0], int)
    # Наблюдение: до IPC оба сообщения делят один dict (в проде data-plane идёт через очередь).
    assert sent[0][1]["data"] is sent[1][1]["data"]

    for _target, msg in sent:
        item, metrics = _deliver(msg)
        assert "_t_sent_ns" not in item
        assert metrics["transport_ms"] > 0.0


def test_t45d_frame_trace_and_transport_stamp_coexist(monkeypatch: pytest.MonkeyPatch) -> None:
    """FW_FRAME_TRACE вкл.: на проводе оба поля (``_t_send`` и ``_t_sent_ns``); после приёма
    оба сняты, а transport-спан трассировки и transport_ms присутствуют."""
    monkeypatch.setattr(frame_trace, "_ENABLED", True)
    sent = _send_through_executor(["out"], [{"frame_id": 7}])
    assert len(sent) == 1
    data = sent[0][1]["data"]
    assert isinstance(data["_t_send"], float)
    assert isinstance(data["_t_sent_ns"], int)

    item, metrics = _deliver(sent[0][1])
    assert "_t_send" not in item and "_t_sent_ns" not in item
    spans = [s for s in item.get("trace", []) if s.get("kind") == "transport"]
    assert len(spans) == 1, f"transport-спан трассировки пропал: {item.get('trace')!r}"
    assert metrics["transport_ms"] > 0.0
