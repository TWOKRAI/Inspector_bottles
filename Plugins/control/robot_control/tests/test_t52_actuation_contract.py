# -*- coding: utf-8 -*-
"""Task 5.2 — слепые приёмочные тесты «Контракта привода» у ``robot_control``.

Источник — только раздел «Task 5.2» плана ``plans/transport-single-policy/phase-5.md``. Реализации на
момент написания нет; тесты красные по построению (``PluginContext.scheduler`` ещё не существует).

Контракт, который пинят тесты:

* в ``process()`` / ``_process_marker`` решателя нет ожидания: отбраковка ставится в планировщик
  (``ctx.scheduler``) по ``capture_ts + transit_ms`` и исполняется им;
* регистры ``transit_ms`` (умолчание 0), ``actuation_tolerance_ms`` (20), deprecated-алиас
  ``reject_delay_ms``: ``effective_transit = transit_ms or reject_delay_ms``;
* значения ``actuation`` в широкой записи: ``scheduled`` / ``missed`` / ``unscheduled`` /
  ``immediate`` / ``none``; запись несёт ``fire_at`` и ``transit_ms``;
* планируется только ``reject``; ``pass`` и pass-маркер в очередь не ставятся;
* запись о разрыве читается без ``5.3``: ``count``, ``first_capture_ts``, ``last_capture_ts``,
  ``trace_ids``, ``reasons``, ``sources``; ОДНА постановка с окном
  ``[first + transit, last + transit]``, ``total_not_inspected += count``; маркер старой формы
  (без ``count``) -> ``count = 1``;
* ``cmd_get_stats``: ``actuation_fired_items``, ``actuation_missed_items``, ``actuation_late_fires``,
  ``actuation_unscheduled_items``, ``actuation_unfired_on_stop_items``.

Контекст — НАСТОЯЩИЙ ``PluginContext`` над ``MockProcessServices`` с ``worker_manager=None`` (юнит-режим:
воркера нет, ``tick()`` зовут руками). Подменён только приёмник широких записей
(``ctx.write_event`` -> список): конверт записи — прикладная часть, а не предмет теста.
Какую роль играет ``fire`` у планировщика процесса, спека не говорит, поэтому исполнение цели
наблюдается ТОЛЬКО через ``cmd_get_stats`` (счётчики) и ``ctx.scheduler.pending()/tick()``.

Подменных часов у планировщика процесса не подставить (создаётся лениво внутри ``PluginContext``),
поэтому времена — настоящие, а цели строятся от ``time.time()`` с запасом >= 10 мс и опросом
с дедлайном 1 с; нижних границ короче 100 мс тесты не утверждают.

Любой вызов, способный блокироваться (сегодня ``process`` спит), идёт в daemon-потоке
с дедлайном на ``join``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockDocumentSink,
    MockProcessServices,
)
from Plugins.control.robot_control.plugin import RobotControlPlugin

STAT_KEYS = (
    "actuation_fired_items",
    "actuation_missed_items",
    "actuation_late_fires",
    "actuation_unscheduled_items",
    "actuation_unfired_on_stop_items",
)


# --- Фикстуры ------------------------------------------------------------------------------------


def _bounded(fn: Callable[[], Any], timeout: float = 30.0) -> Any:
    """Вызов в daemon-потоке с дедлайном на join: зависание = падение, а не висящий прогон."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросим в поток теста
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов завис дольше {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _plugin(config: Dict[str, Any] | None = None, *, with_sink: bool = False):
    """(плагин, настоящий ctx, сервисы, список широких записей).

    ``worker_manager=None`` ставится ДО создания контекста: он читает его в ``__init__``.
    """
    svc = MockProcessServices(name="inspector", document_sink=MockDocumentSink() if with_sink else None)
    svc.worker_manager = None  # type: ignore[assignment]
    ctx = PluginContext(svc, config=dict(config or {}), plugin_name="robot_control")
    events: List[Dict[str, Any]] = []

    def write_event(
        kind: str, summary: str = "", /, *, unit: Any = None, decisive: bool = False, **fields: Any
    ) -> bool:
        events.append({"kind": kind, "summary": summary, "decisive": decisive, "unit": unit, **fields})
        return True

    ctx.write_event = write_event  # type: ignore[method-assign]
    plugin = RobotControlPlugin()
    plugin.configure(ctx)
    return plugin, ctx, svc, events


def _reject_item(capture_ts: float | None, trace: str = "t1") -> dict:
    item: dict = {
        "frame": np.zeros((8, 8, 3), dtype=np.uint8),
        "detections": [{"bbox": [1, 1, 5, 5], "center": [3, 3], "area": 900}],
        "trace_id": trace,
    }
    if capture_ts is not None:
        item["capture_ts"] = capture_ts
    return item


def _pass_item(capture_ts: float | None = None, trace: str = "p1") -> dict:
    item: dict = {"frame": np.zeros((8, 8, 3), dtype=np.uint8), "detections": [], "trace_id": trace}
    if capture_ts is not None:
        item["capture_ts"] = capture_ts
    return item


def _old_marker(capture_ts: float | None, trace: str = "m1", reason: str = "lag") -> dict:
    """Маркер СТАРОЙ формы (4.7d-1): без ``count`` и без ``first/last_capture_ts``."""
    marker: dict = {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": reason,
        "source": "processor_0",
        "trace_id": trace,
    }
    if capture_ts is not None:
        marker["capture_ts"] = capture_ts
    return marker


def _gap_record(count: int, first: float | None, last: float | None) -> dict:
    """Запись о разрыве: форма из acceptance 5.3 (count, trace_ids, first/last_capture_ts, reasons, sources)."""
    record: dict = {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "count": count,
        "trace_ids": [f"gap-{i}" for i in range(count)],
        "reasons": {"lag": count - 78, "stale_restore": 78} if count > 78 else {"lag": count},
        "sources": {"processor_0": count},
    }
    if first is not None:
        record["first_capture_ts"] = first
    if last is not None:
        record["last_capture_ts"] = last
    return record


def _drain(ctx: PluginContext, timeout: float = 1.0) -> int:
    """Звать ``tick()`` вручную, пока куча не опустеет; вернуть число выстрелов (записей)."""
    fired = 0
    deadline = time.perf_counter() + timeout
    while ctx.scheduler.pending() > 0 and time.perf_counter() < deadline:
        fired += ctx.scheduler.tick()
        time.sleep(0.005)
    return fired


def _stat(plugin: RobotControlPlugin, key: str) -> Any:
    return plugin.cmd_get_stats({}).get(key)


def _p99(values: List[float]) -> float:
    ordered = sorted(values)
    return ordered[int(len(ordered) * 0.99) - 1]


# --- process() не ждёт: p99 < 1 мс, pending +1 на каждый отбракованный -----------------------------


@pytest.mark.parametrize("kind", ["reject", "marker"])
def test_process_p99_below_1ms_and_pending_grows_by_exactly_one_per_call(kind: str) -> None:
    plugin, ctx, _, _ = _plugin({"transit_ms": 100})
    durations: List[float] = []
    pendings: List[int] = []

    def run() -> None:
        for i in range(1000):
            ts = time.time()
            item = _reject_item(ts, f"t{i}") if kind == "reject" else _old_marker(ts, f"m{i}")
            t0 = time.perf_counter()
            out = plugin.process([item])
            durations.append(time.perf_counter() - t0)
            assert len(out) == 1
            pendings.append(ctx.scheduler.pending())

    _bounded(run, timeout=60.0)

    assert pendings == list(range(1, 1001)), "pending() вырос не ровно на 1 после каждого вызова"
    p99_ms = _p99(durations) * 1000.0
    assert p99_ms < 1.0, f"p99 process() = {p99_ms:.3f} мс при transit_ms=100 (ожидалось < 1 мс)"


# --- Значения actuation --------------------------------------------------------------------------


def test_pass_is_never_scheduled_and_record_says_none() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})

    out = plugin.process([_pass_item(time.time())])

    assert out[0]["inspection_result"]["action"] == "pass"  # якорь: это решение pass
    assert ctx.scheduler.pending() == 0
    assert events[-1]["actuation"] == "none"


def test_pass_marker_is_never_scheduled_and_record_says_none() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100, "not_inspected_action": "pass"})

    out = plugin.process([_old_marker(time.time())])

    assert out[0]["inspection_result"]["action"] == "pass"
    assert ctx.scheduler.pending() == 0
    assert events[-1]["actuation"] == "none"


@pytest.mark.parametrize("kind", ["reject", "marker"])
def test_transit_zero_is_immediate_fires_synchronously_and_never_creates_the_scheduler(kind: str) -> None:
    plugin, ctx, svc, events = _plugin({"transit_ms": 0})
    item = _reject_item(time.time()) if kind == "reject" else _old_marker(time.time())

    out = plugin.process([item])

    assert out[0]["inspection_result"]["action"] == "reject"  # якорь
    assert events[-1]["actuation"] == "immediate"
    assert _stat(plugin, "actuation_fired_items") == 1  # fire синхронно, без tick()
    # при transit == 0 планировщик не используется и не создаётся (ленивое свойство не тронуто)
    assert getattr(svc, "_actuation_scheduler", None) is None
    assert ctx.scheduler.pending() == 0


def test_default_config_has_transit_zero_so_reject_is_immediate() -> None:
    plugin, _, _, events = _plugin({})

    plugin.process([_reject_item(time.time())])

    assert events[-1]["actuation"] == "immediate"
    assert _stat(plugin, "actuation_fired_items") == 1


@pytest.mark.parametrize("kind", ["reject", "marker"])
def test_fresh_reject_is_scheduled_with_fire_at_and_transit_in_the_wide_record(kind: str) -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    capture_ts = time.time()
    item = _reject_item(capture_ts) if kind == "reject" else _old_marker(capture_ts)

    plugin.process([item])

    rec = events[-1]
    assert rec["actuation"] == "scheduled"
    assert rec["transit_ms"] == 100
    assert rec["fire_at"] == pytest.approx(capture_ts + 0.100, abs=0.010)
    assert ctx.scheduler.pending() == 1


def test_scheduled_reject_fires_when_due_and_counts_one_fired_item() -> None:
    plugin, ctx, _, _ = _plugin({"transit_ms": 100})
    plugin.process([_reject_item(time.time() - 0.090)])  # цель наступит через ~10 мс
    assert ctx.scheduler.pending() == 1

    _drain(ctx)

    assert ctx.scheduler.pending() == 0
    assert _stat(plugin, "actuation_fired_items") == 1
    assert _stat(plugin, "actuation_missed_items") == 0


def test_stale_reject_is_missed_counted_and_never_fires() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})

    plugin.process([_reject_item(time.time() - 5.0)])  # окно закрылось 4.9 с назад

    assert events[-1]["actuation"] == "missed"
    assert ctx.scheduler.pending() == 0
    assert _stat(plugin, "actuation_missed_items") == 1
    ctx.scheduler.tick()
    assert _stat(plugin, "actuation_fired_items") == 0


@pytest.mark.parametrize("kind", ["reject", "marker"])
def test_item_without_capture_ts_is_unscheduled_counted_and_never_queued(kind: str) -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    item = _reject_item(None) if kind == "reject" else _old_marker(None)

    out = plugin.process([item])

    assert out[0]["inspection_result"]["action"] == "reject"  # якорь: решение вынесено
    assert events[-1]["actuation"] == "unscheduled"
    assert _stat(plugin, "actuation_unscheduled_items") == 1
    assert ctx.scheduler.pending() == 0
    ctx.scheduler.tick()
    assert _stat(plugin, "actuation_fired_items") == 0


def test_gap_record_without_timestamps_adds_its_whole_count_to_unscheduled_items() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})

    plugin.process([_gap_record(1078, None, None)])

    assert events[-1]["actuation"] == "unscheduled"
    assert _stat(plugin, "actuation_unscheduled_items") == 1078
    assert ctx.scheduler.pending() == 0


# --- Запись о разрыве: одна постановка на окно, count суммируется --------------------------------


def test_gap_record_is_one_scheduling_one_fire_with_the_full_count() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    last = time.time() - 0.050
    first = last - 10.77  # 1078 кадров по 100 FPS

    out = plugin.process([_gap_record(1078, first, last)])

    assert len(out) == 1
    assert ctx.scheduler.pending() == 1, "запись о разрыве должна дать ОДНУ постановку, а не по кадру"
    assert events[-1]["actuation"] == "scheduled"
    assert _stat(plugin, "total_not_inspected") == 1078

    fires = _drain(ctx)

    assert fires == 1, f"на окно разрыва ожидался один выстрел, было {fires}"
    assert _stat(plugin, "actuation_fired_items") == 1078
    assert _stat(plugin, "actuation_missed_items") == 0


def test_gap_record_wide_event_carries_count_and_trace_ids_list() -> None:
    plugin, _, _, events = _plugin({"transit_ms": 100})
    last = time.time() - 0.050
    gap = _gap_record(1078, last - 10.77, last)

    plugin.process([gap])

    rec = events[-1]
    assert rec["count"] == 1078
    assert rec["trace_ids"] == gap["trace_ids"]
    assert len(rec["trace_ids"]) == 1078
    assert not (rec["unit"] or {}).get("trace_id"), "у записи о разрыве trace_id пуст: имена — в trace_ids"


def test_gap_window_end_is_last_capture_plus_transit_not_first() -> None:
    """Окно ``[first + transit, last + transit]``: закрывает его ``last``, а не ``first``."""
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    now = time.time()
    # first+transit давно позади (now-19.9), но last+transit == now: окно ЕЩЁ открыто
    plugin.process([_gap_record(1078, now - 20.0, now - 0.100)])

    assert events[-1]["actuation"] == "scheduled"
    assert ctx.scheduler.pending() == 1
    assert _stat(plugin, "actuation_missed_items") == 0


def test_gap_record_with_a_closed_window_is_missed_with_its_whole_count() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    now = time.time()

    plugin.process([_gap_record(1078, now - 20.0, now - 5.0)])  # last+transit = now-4.9 с: закрыто

    assert events[-1]["actuation"] == "missed"
    assert _stat(plugin, "actuation_missed_items") == 1078
    assert ctx.scheduler.pending() == 0
    assert _stat(plugin, "total_not_inspected") == 1078


def test_total_not_inspected_grows_by_count_across_records() -> None:
    plugin, _, _, _ = _plugin({"transit_ms": 100})
    now = time.time()

    plugin.process([_gap_record(1078, now - 20.0, now - 0.1)])
    plugin.process([_old_marker(now)])
    plugin.process([_gap_record(12, now - 1.0, now - 0.1)])

    assert _stat(plugin, "total_not_inspected") == 1078 + 1 + 12


def test_old_form_marker_without_count_means_count_one() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})

    plugin.process([_old_marker(time.time())])

    assert events[-1]["actuation"] == "scheduled"
    assert _stat(plugin, "total_not_inspected") == 1
    assert ctx.scheduler.pending() == 1
    _drain(ctx)
    assert _stat(plugin, "actuation_fired_items") == 1


def test_gap_record_does_not_touch_inspected_counters_or_the_reject_front() -> None:
    """Фронт ``_rejecting`` и счётчики осмотра запись о разрыве не трогает (как маркер 4.7d-4)."""
    plugin, _, _, _ = _plugin({"transit_ms": 100}, with_sink=True)
    now = time.time()

    plugin.process([_reject_item(now, "d1")])  # фронт: первый вердикт
    plugin.process([_gap_record(50, now - 1.0, now - 0.05)])  # разрыв посреди серии брака
    plugin.process([_reject_item(now, "d2")])  # продолжение серии: второго вердикта быть не должно

    stats = plugin.cmd_get_stats({})
    assert stats["total_inspected"] == 2
    assert stats["total_rejected"] == 2
    assert stats["verdicts_written"] == 1


# --- Вердикт остаётся на решении, fire пишет только счётчики -------------------------------------


def test_verdict_is_written_at_decision_time_and_fire_adds_no_documents() -> None:
    plugin, ctx, svc, _ = _plugin({"transit_ms": 100}, with_sink=True)
    now = time.time()
    for i in range(3):
        plugin.process([_reject_item(now - 0.090, f"t{i}")])

    assert len(svc.document_sink.documents) == 1  # якорь: фронт дал один документ ДО выстрелов
    assert svc.document_sink.documents[0]["action"] == "reject"

    _drain(ctx)

    assert _stat(plugin, "actuation_fired_items") == 3
    assert len(svc.document_sink.documents) == 1, "fire не должен писать вердикт-документы"


# --- Алиас reject_delay_ms -----------------------------------------------------------------------


def _reject_delay_warnings(svc: MockProcessServices) -> list:
    return [e for e in svc.logs if e["level"] == "WARNING" and "reject_delay_ms" in e["msg"]]


def test_reject_delay_alias_acts_as_transit_and_warns_exactly_once_per_100_calls() -> None:
    plugin, ctx, svc, events = _plugin({"reject_delay_ms": 50, "transit_ms": 0})

    def run() -> None:
        for i in range(100):
            plugin.process([_reject_item(time.time(), f"t{i}")])

    _bounded(run, timeout=60.0)  # сегодня каждый вызов спит 50 мс

    assert ctx.scheduler.pending() == 100  # поведение transit_ms=50: каждый брак поставлен
    assert events[-1]["actuation"] == "scheduled"
    assert events[-1]["transit_ms"] == 50
    assert len(_reject_delay_warnings(svc)) == 1, [e["msg"] for e in _reject_delay_warnings(svc)]


def test_reject_delay_alias_sets_fire_at_to_capture_plus_50ms() -> None:
    plugin, _, _, events = _plugin({"reject_delay_ms": 50, "transit_ms": 0})
    capture_ts = time.time()

    plugin.process([_reject_item(capture_ts)])

    assert events[-1]["fire_at"] == pytest.approx(capture_ts + 0.050, abs=0.010)


def test_transit_ms_wins_over_reject_delay_ms_when_both_are_set() -> None:
    plugin, _, _, events = _plugin({"transit_ms": 100, "reject_delay_ms": 50})

    plugin.process([_reject_item(time.time())])

    assert events[-1]["transit_ms"] == 100  # effective_transit = transit_ms or reject_delay_ms


def test_no_reject_delay_warning_without_the_alias() -> None:
    plugin, ctx, svc, _ = _plugin({"transit_ms": 100})

    for i in range(100):
        plugin.process([_reject_item(time.time(), f"t{i}")])

    assert ctx.scheduler.pending() == 100  # якорь: вызовы действительно прошли планировщик
    assert _reject_delay_warnings(svc) == []


def test_set_delay_command_writes_transit_ms_and_warns_that_it_is_deprecated() -> None:
    plugin, ctx, svc, events = _plugin({})

    result = plugin.cmd_set_delay({"delay_ms": 70})
    plugin.process([_reject_item(time.time())])

    assert result["status"] == "ok"
    assert events[-1]["transit_ms"] == 70  # set_delay пишет transit_ms
    assert ctx.scheduler.pending() == 1
    warnings = [e for e in svc.logs if e["level"] == "WARNING" and "set_delay" in e["msg"]]
    assert len(warnings) >= 1


# --- cmd_get_stats -------------------------------------------------------------------------------


def test_cmd_get_stats_has_the_five_literal_actuation_keys_all_zero_at_start() -> None:
    plugin, _, _, _ = _plugin({"transit_ms": 100})

    stats = plugin.cmd_get_stats({})

    for key in STAT_KEYS:
        assert key in stats, f"в cmd_get_stats нет ключа {key}"
        assert stats[key] == 0
    assert "missed_actuation" not in stats  # старый термин не используется


def test_cmd_get_stats_counts_each_outcome_under_its_own_key() -> None:
    plugin, ctx, _, _ = _plugin({"transit_ms": 100})
    now = time.time()
    plugin.process([_reject_item(now - 0.090, "fires")])  # будет выстрел
    plugin.process([_reject_item(now - 5.0, "late")])  # missed
    plugin.process([_reject_item(None, "nots")])  # unscheduled
    _drain(ctx)

    stats = plugin.cmd_get_stats({})

    assert stats["actuation_fired_items"] == 1
    assert stats["actuation_missed_items"] == 1
    assert stats["actuation_unscheduled_items"] == 1
    assert stats["actuation_late_fires"] == 0
    assert stats["actuation_unfired_on_stop_items"] == 0


# --- capture_ts доезжает через настоящий PluginRunner --------------------------------------------


class _FreshDictUpstream:
    """Плагин, строящий СВЕЖИЙ выходной dict (как stitcher/line_filter): сам ``capture_ts`` не копирует."""

    name = "fresh_dict_upstream"
    enabled = True
    inputs: list = []
    outputs: list = []

    def process(self, items: list[dict]) -> list[dict]:
        return [{"detections": it["detections"], "frame": it["frame"]} for it in items]


def test_capture_ts_reaches_the_solver_through_the_real_plugin_runner() -> None:
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    runner = PluginRunner(validate_ports=False)
    capture_ts = time.time()
    upstream_in = [_reject_item(capture_ts, "carried")]

    upstream_out = runner.call_process(_FreshDictUpstream(), upstream_in)  # type: ignore[arg-type]
    assert upstream_out[0].get("capture_ts") == capture_ts  # якорь: перенос системных полей работает

    plugin.process(upstream_out)

    assert events[-1]["actuation"] == "scheduled", "capture_ts не дошёл до решателя: запись не поставлена"
    assert ctx.scheduler.pending() == 1


# --- Ревью 5.2, находка 4: полный литерал записи о разрыве из acceptance 5.3 -------------------------


def test_gap_record_full_literal_of_task_5_3_with_single_source_uses_the_source_key() -> None:
    """Литерал ``build_gap`` из acceptance 5.3: один узел-источник -> есть ``source`` и ``camera_id``.

    Покрывает ветку ``item["source"]`` у записи с ``count > 1`` (фикстура ``_gap_record`` её не несёт).
    """
    plugin, ctx, _, events = _plugin({"transit_ms": 100})
    ts3 = time.time() - 0.050
    ts1 = ts3 - 0.020
    record = {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "count": 3,
        "trace_ids": ["t1", "t2", "t3"],
        "first_capture_ts": ts1,
        "last_capture_ts": ts3,
        "reasons": {"lag": 2, "stale_restore": 1},
        "sources": {"processor_0": 3},
        "source": "processor_0",
        "camera_id": "cam_0",
    }

    out = plugin.process([record])

    result = out[0]["inspection_result"]
    assert result["action"] == "reject"
    assert result["source"] == "processor_0"  # одиночный источник — строкой, не гистограммой
    assert result["origin"] == {"lag": 2, "stale_restore": 1}  # reason нет -> гистограмма причин
    rec = events[-1]
    assert rec["actuation"] == "scheduled"
    assert rec["count"] == 3
    assert rec["trace_ids"] == ["t1", "t2", "t3"]
    assert rec["fire_at"] == pytest.approx(ts1 + 0.100, abs=1e-9)
    assert "processor_0@" not in rec["summary"] and "@processor_0" in rec["summary"]
    assert ctx.scheduler.pending() == 1
    assert _stat(plugin, "total_not_inspected") == 3
