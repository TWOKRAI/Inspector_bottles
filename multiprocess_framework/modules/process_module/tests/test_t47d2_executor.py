# -*- coding: utf-8 -*-
"""Task 4.7d-2 — слепые приёмочные тесты ``PipelineExecutor``: проход маркера и рождение ``stale_exec``.

Независимый tester, от acceptance 4.7d-2 (plans/transport-single-policy/task-4.7.md), без чтения
реализации 4.7d-2 (её в дереве нет). Ожидаемые значения — литералы из acceptance.

Что пинится (исполнитель):
  * коллекция из одних маркеров идёт мимо плагинов без ``accepts_markers`` (process 0 раз, breaker не
    тронут, ``SuspectTagStep`` не перетирает тег ``not_inspected`` на ``suspect``) и уходит по всем
    ``chain_targets``; ``not_inspected_handled`` растёт;
  * плагин с ``accepts_markers = True`` получает маркер ровно 1 раз и тот же объект; под
    ``FW_PORT_VALIDATE=1`` на маркере нет ``PortValidationError`` и ``consecutive_fails`` не растёт;
  * stale-дроп батча считает ВХОДНЫЕ items (pre-chain 3, post-chain 2->1 = 2, 1->3 = 1, [] = 1) в обоих
    режимах; под ``every`` на каждый вход рождается маркер ``stale_exec`` (pre-chain — через
    ``_forward_markers``, post-chain — прямо в ``_send_results``, плагин на входах вызван 1 раз);
  * батч с неизменёнными view даёт 0 маркеров; ``overflow`` вне ("latest", "every") -> ``ValueError``.

Стенд stale-сценариев: реальный ``FrameShmMiddleware`` (писатель A -> читатель B) из
router_module/tests/test_frame_ref_gen.py, реальный ``PipelineExecutor.run`` в daemon-потоке с дедлайном.
Зелёные контроли (держат стенд честным): stale под latest pre-chain 3 и post-chain [] (+1), батч с
неизменёнными view.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Callable

import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker, is_marker
from multiprocess_framework.modules.router_module.tests import test_frame_ref_gen as _T

DEADLINE_S = 15.0
SERVICE_KEYS = {"_t_sent_ns", "_t_send", "_from"}  # штамп transport_ms и frame-trace: не часть маркера


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


class _Plugin:
    """Плагин-шпион: считает вызовы process(), запоминает входной список items, возвращает ``fn(items)``
    (по умолчанию — вход как есть), перед возвратом зовёт ``on_process`` (перезапись слота во время цепочки)."""

    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(
        self,
        name: str,
        *,
        accepts: bool | None = None,
        fn: Callable[[list[dict]], list[dict]] | None = None,
        on_process: Callable[[], None] | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
    ) -> None:
        self.name = name
        if accepts is not None:
            self.accepts_markers = accepts
        self._fn = fn
        self._on_process = on_process
        self.calls = 0
        self.seen: list[list[dict]] = []
        if inputs is not None:
            self.inputs = inputs
        if outputs is not None:
            self.outputs = outputs

    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        self.seen.append(list(items))
        if self._on_process is not None:
            self._on_process()
        return self._fn(items) if self._fn is not None else items


class _Failing(_Plugin):
    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        raise ValueError("intentional failure")


def _executor(plugins, *, shm=None, overflow="latest", targets=("out",), sent=None, **kw) -> PipelineExecutor:
    sent = sent if sent is not None else []
    return PipelineExecutor(
        plugins=list(plugins),
        chain_targets=list(targets),
        shm_middleware=shm,
        send_fn=lambda target, msg: sent.append((target, msg)),
        node_name="exec_node",
        overflow=overflow,
        **kw,
    )


def _drive(ex: PipelineExecutor, batches: list[list[dict]]) -> None:
    """Прогнать батчи через настоящий ``ex.run`` и остановить воркер после того, как очередь выбрана
    (текущий такт воркер доделывает целиком — stop проверяется между тактами)."""
    q: queue.Queue = queue.Queue()
    for b in batches:
        q.put(b)
    ex.bind_queue(q)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
    worker.start()
    deadline = threading.Event()
    for _ in range(int(DEADLINE_S / 0.01)):
        if q.empty():
            break
        deadline.wait(0.01)
    else:
        stop.set()
        pytest.fail("исполнитель не выбрал очередь за дедлайн")
    stop.set()
    worker.join(DEADLINE_S)
    if worker.is_alive():
        pytest.fail("PipelineExecutor не завершил такт за дедлайн")


def _data(sent: list[tuple[str, dict]]) -> list[dict]:
    return [m["data"] for _t, m in sent]


def _bare(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in SERVICE_KEYS}


def _marker(trace_id: str = "m1") -> dict:
    return build_marker({"trace_id": trace_id, "capture_ts": 5.0, "camera_id": "cam0"}, reason="lag", source="upstream")


# --------------------------------------------------------------------------------------------
# проход маркера
# --------------------------------------------------------------------------------------------
def test_marker_collection_skips_plain_plugin_and_suspect_step_and_goes_to_every_target():
    """Исполнитель, маркер-коллекция, плагин без accepts_markers (в цепочке критический bypassed плагин):
    process вызван 0 раз, consecutive_fails не изменился, inspection_status == "not_inspected" (не
    "suspect"); send_fn получила по сообщению на каждый chain_targets, data равен маркеру (кроме служебных
    _t_sent_ns / frame-trace штампа); not_inspected_handled +1."""
    crit = _Failing("crit")
    plain = _Plugin("plain")
    sent: list = []
    ex = _executor([crit, plain], targets=("t1", "t2"), sent=sent, max_consecutive_fails=1, critical_plugins=["crit"])
    ex._execute_chain([{"frame": "x", "trace_id": "n1"}])  # breaker критического плагина открыт
    assert ex.is_bypassed("crit")
    calls_before = plain.calls
    fails_before = dict(ex._consecutive_fails)
    handled_before = ex.get_cycle_metrics().get("not_inspected_handled", 0)

    marker = _marker("m1")
    _drive(ex, [[marker]])

    assert plain.calls == calls_before, "плагин без accepts_markers вызван на маркере"
    assert ex._consecutive_fails == fails_before
    assert [t for t, _m in sent] == ["t1", "t2"]
    for item in _data(sent):
        assert item["inspection_status"] == "not_inspected"
        assert _bare(item) == {
            "inspection_status": "not_inspected",
            "overflow_marker": True,
            "reason": "lag",
            "source": "upstream",
            "trace_id": "m1",
            "capture_ts": 5.0,
            "camera_id": "cam0",
        }
    assert ex.get_cycle_metrics()["not_inspected_handled"] == handled_before + 1


def test_plugin_with_accepts_markers_gets_the_marker_exactly_once_same_object():
    """Плагин с accepts_markers = True получает маркер-item в process ровно 1 раз (spy), тот же объект данных."""
    spy = _Plugin("keeper", accepts=True)
    marker = _marker("m1")
    ex = _executor([spy])

    _drive(ex, [[marker]])

    assert spy.calls == 1
    assert len(spy.seen[0]) == 1 and spy.seen[0][0] is marker


def test_port_validate_does_not_apply_to_marker_items(monkeypatch):
    """FW_PORT_VALIDATE=1, плагин с accepts_markers = True и обязательными портами frame/detections, маркер
    на входе: process вызван 1 раз, PortValidationError нет, consecutive_fails не изменился."""
    monkeypatch.setenv("FW_PORT_VALIDATE", "1")
    ports = [Port(name="frame", dtype="image/bgr"), Port(name="detections", dtype="any")]
    spy = _Plugin("robot", accepts=True, inputs=list(ports), outputs=list(ports))
    errors: list[str] = []
    ex = _executor([spy], log_error=errors.append)

    _drive(ex, [[_marker("m1")]])

    assert spy.calls == 1
    assert ex._consecutive_fails.get("robot", 0) == 0
    assert not any("PortValidationError" in e for e in errors), errors


# --------------------------------------------------------------------------------------------
# stale в _run_batch
# --------------------------------------------------------------------------------------------
def _view_items(writer, reader, n: int) -> list[dict]:
    """n входных items со zero-copy view (trace_id t1..tn, capture_ts 1.0..n) — как после DataReceiver."""
    items = []
    for i in range(1, n + 1):
        wire = _T._wire(
            _T._send(writer, {"frame": _T._arr("frame", i), "trace_id": f"t{i}", "capture_ts": float(i), "n": i})
        )
        items.append(_T._receive_as_pipeline(reader, wire))
    assert all(it.get("_shm_views") for it in items), "стенд неисправен: у входа нет view"
    return items


def _stale_run(rig, *, overflow: str, kind: str, n_in: int, accepts: bool = False):
    """Один stale-сценарий. kind: 'pre' (слот перезаписан до такта) | 'post_merge' (плагин склеивает все
    входы в 1 выход, слот перезаписан во время process) | 'post_fan3' (1 вход -> 3 выхода) | 'post_empty'
    (плагин вернул []). Возвращает (executor, plugin, sent, Δframe_stale_drops)."""
    writer, reader = rig.make("A"), rig.make("B")
    items = _view_items(writer, reader, n_in)
    fns = {
        "pre": None,
        "post_merge": lambda its: [{"frame": its[0]["frame"], "n": 0}],
        "post_fan3": lambda its: [{"frame": its[0]["frame"], "n": i} for i in range(3)],
        "post_empty": lambda its: [],
    }
    overwrite = (lambda: _T._overwrite(writer, "frame")) if kind != "pre" else None
    plugin = _Plugin("p", accepts=accepts, fn=fns[kind], on_process=overwrite)
    sent: list = []
    ex = _executor([plugin], shm=reader, overflow=overflow, sent=sent)
    if kind == "pre":
        _T._overwrite(writer, "frame")
    before = reader.frame_stale_drops
    _drive(ex, [items])
    return ex, plugin, sent, reader.frame_stale_drops - before


def _assert_markers(sent: list, trace_ids: list[str]) -> None:
    data = _data(sent)
    assert [d.get("trace_id") for d in data] == trace_ids
    assert all(is_marker(d) for d in data), f"среди отправленного есть не-маркеры: {data}"
    assert all(d["reason"] == "stale_exec" for d in data)
    assert all("frame" not in d and "_shm_views" not in d for d in data)


def test_stale_pre_chain_every_three_inputs_three_markers(rig):
    """Stale pre-chain, every, батч из 3 items (t1,t2,t3) со view, слот перезаписан до такта: цепочка не
    вызывалась (spy 0), send_fn получила 3 сообщения-маркера (stale_exec, t1,t2,t3 по порядку),
    frame_stale_drops +3, not_inspected_stale_exec == 3, not_inspected_handled +3."""
    ex, plugin, sent, d_stale = _stale_run(rig, overflow="every", kind="pre", n_in=3)

    assert plugin.calls == 0
    _assert_markers(sent, ["t1", "t2", "t3"])
    assert d_stale == 3
    metrics = ex.get_cycle_metrics()
    assert metrics["not_inspected_stale_exec"] == 3
    assert metrics["not_inspected_handled"] == 3


@pytest.mark.parametrize("accepts", [False, True], ids=["plain_plugin", "accepts_markers_plugin"])
def test_stale_post_chain_every_2_to_1_counts_inputs_and_sends_markers_directly(rig, accepts):
    """Stale post-chain 2->1 (плагин склеивает 2 входа в 1 выход, слот перезаписан во время process), every:
    send_fn получила 2 маркера (t1,t2) и 0 обычных, frame_stale_drops +2 (было +1 по выходам),
    not_inspected_stale_exec == 2, not_inspected_handled +2; плагин (в т.ч. с accepts_markers = True)
    вызван ровно 1 раз — на входах, маркеры его повторно не проходят."""
    ex, plugin, sent, d_stale = _stale_run(rig, overflow="every", kind="post_merge", n_in=2, accepts=accepts)

    _assert_markers(sent, ["t1", "t2"])
    assert plugin.calls == 1
    assert d_stale == 2
    metrics = ex.get_cycle_metrics()
    assert metrics["not_inspected_stale_exec"] == 2
    assert metrics["not_inspected_handled"] == 2


def test_stale_post_chain_every_1_to_3_counts_one_input_one_marker(rig):
    """Stale post-chain 1->3 (every): frame_stale_drops +1 (было +3), 1 маркер."""
    ex, plugin, sent, d_stale = _stale_run(rig, overflow="every", kind="post_fan3", n_in=1)

    _assert_markers(sent, ["t1"])
    assert d_stale == 1
    assert ex.get_cycle_metrics()["not_inspected_stale_exec"] == 1


def test_stale_post_chain_every_empty_output_still_counts_input_and_sends_marker(rig):
    """Stale post-chain, плагин вернул [], слот перезаписан (every): frame_stale_drops +1 (вход), 1 маркер."""
    ex, plugin, sent, d_stale = _stale_run(rig, overflow="every", kind="post_empty", n_in=1)

    _assert_markers(sent, ["t1"])
    assert d_stale == 1
    assert ex.get_cycle_metrics()["not_inspected_stale_exec"] == 1


@pytest.mark.parametrize(
    ("kind", "n_in", "expected_drops"),
    [("pre", 3, 3), ("post_merge", 2, 2), ("post_fan3", 1, 1)],
    ids=["pre_3", "post_2_to_1", "post_1_to_3"],
)
def test_stale_latest_counts_inputs_and_sends_nothing(rig, kind, n_in, expected_drops):
    """Те же три сценария (pre 3, post 2->1, post 1->3) при latest: send_fn не вызывалась, frame_stale_drops
    +3 / +2 / +1, ключа not_inspected_stale_exec нет, not_inspected_handled не вырос."""
    ex, _plugin, sent, d_stale = _stale_run(rig, overflow="latest", kind=kind, n_in=n_in)

    assert sent == []
    assert d_stale == expected_drops
    metrics = ex.get_cycle_metrics()
    assert "not_inspected_stale_exec" not in metrics
    assert metrics.get("not_inspected_handled", 0) == 0


def test_stale_post_chain_latest_empty_output_counts_one_input_control(rig):
    """Stale post-chain, плагин вернул [], latest: frame_stale_drops +1 (reader уже считает вход), ничего не
    отправлено, ключа not_inspected_stale_exec нет. Решение 4.7d шаг 6 («оба режима») — не отдельная строка
    acceptance; зелёный и до реализации."""
    ex, _plugin, sent, d_stale = _stale_run(rig, overflow="latest", kind="post_empty", n_in=1)

    assert sent == []
    assert d_stale == 1
    assert "not_inspected_stale_exec" not in ex.get_cycle_metrics()


@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_unchanged_views_batch_yields_no_markers_and_ordinary_results(rig, overflow):
    """Батч с неизменёнными view: маркеров 0, обычные результаты уходят как раньше (control: зелёный и до
    реализации). Ожидаемое Δframe_stale_drops == 0, ровно одно обычное сообщение."""
    writer, reader = rig.make("A"), rig.make("B")
    items = _view_items(writer, reader, 1)
    plugin = _Plugin("p")
    sent: list = []
    ex = _executor([plugin], shm=reader, overflow=overflow, sent=sent)
    before = reader.frame_stale_drops

    _drive(ex, [items])

    data = _data(sent)
    assert len(data) == 1
    assert not is_marker(data[0])
    assert data[0]["trace_id"] == "t1" and data[0]["n"] == 1
    assert reader.frame_stale_drops == before
    metrics = ex.get_cycle_metrics()
    assert metrics.get("not_inspected_handled", 0) == 0
    assert metrics.get("not_inspected_stale_exec", 0) == 0


# --------------------------------------------------------------------------------------------
# конструктор
# --------------------------------------------------------------------------------------------
def test_executor_rejects_unknown_overflow():
    """PipelineExecutor(..., overflow="sometimes") -> ValueError."""
    with pytest.raises(ValueError):
        PipelineExecutor(
            plugins=[],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
            overflow="sometimes",
        )
