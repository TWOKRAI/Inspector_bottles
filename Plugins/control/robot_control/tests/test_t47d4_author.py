# -*- coding: utf-8 -*-
"""Task 4.7d-4 — авторские тесты опасных мест ветки маркера (дополняют слепые).

Опасности механизма:
  (a) маркер посреди серии брака не должен сбросить фронт ``_rejecting``: иначе следующий
      дефектный кадр даст ВТОРОЙ вердикт об одном изделии;
  (b) ``total_not_inspected`` — часть счётчиков статистики и обнуляется вместе с ними;
  (c) выключение плагина посреди серии: обычный item в выключенном плагине сбрасывает фронт,
      маркер — нет (он вообще не «осмотр»). Ветка маркера идёт первой и не должна унаследовать
      сброс из ветки disabled.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from .test_t47d4_marker_policy import _defect_item, _marker, _plugin


def test_marker_between_two_defects_keeps_exactly_one_verdict_document() -> None:
    p, ctx = _plugin()

    p.process([_defect_item(trace="d1")])
    p.process([_marker(trace="m1")])
    p.process([_defect_item(trace="d2")])

    assert len(ctx.documents) == 1
    assert p._verdicts_written == 1
    assert p._total_rejected == 2  # оба дефектных кадра посчитаны, маркер — нет
    assert p._total_inspected == 2


def test_reset_counters_zeroes_total_not_inspected() -> None:
    p, _ = _plugin()
    p.process([_marker(trace="t1")])
    p.process([_marker(trace="t2")])
    assert p.cmd_get_stats({})["total_not_inspected"] == 2  # якорь: счётчик жив до сброса

    p.cmd_reset_counters({})

    assert p.cmd_get_stats({})["total_not_inspected"] == 0


def test_marker_while_disabled_does_not_reset_front_then_reenabled_defect_gives_no_second_verdict() -> None:
    p, ctx = _plugin()
    p.process([_defect_item(trace="d1")])
    assert p._rejecting is True

    p.cmd_disable({})
    out = p.process([_marker(trace="m1")])
    assert out[0]["inspection_result"]["reason"] == "disabled"  # якорь: маркер ушёл по ветке disabled
    assert p._rejecting is True

    p.cmd_enable({})
    p.process([_defect_item(trace="d2")])

    assert len(ctx.documents) == 1
    assert p._total_not_inspected == 1
    assert p._total_inspected == 2


def test_disabled_plugin_marker_takes_no_reject_delay() -> None:
    p, _ = _plugin({"enabled": False, "reject_delay_ms": 400})
    box: dict = {}

    def call() -> None:
        t0 = time.perf_counter()
        box["out"] = p.process([_marker()])
        box["elapsed"] = time.perf_counter() - t0

    th = threading.Thread(target=call, daemon=True)
    th.start()
    th.join(10.0)
    assert not th.is_alive(), "process завис"
    assert box["out"][0]["inspection_result"]["reason"] == "disabled"  # якорь: ветка disabled
    assert box["elapsed"] < 0.2, f"задержка применена к маркеру выключенного плагина: {box['elapsed'] * 1000:.1f} мс"


def test_marker_wide_record_message_names_its_type_and_origin() -> None:
    p, ctx = _plugin()

    p.process([_marker(reason="lag")])

    assert ctx.events[0]["summary"] == "reject: не проверен (lag@processor_0)"


def test_disabled_marker_wide_record_message_still_names_marker() -> None:
    p, ctx = _plugin({"enabled": False})

    p.process([_marker(reason="door")])

    assert ctx.events[0]["summary"] == "pass: не проверен (door@processor_0)"


def test_regular_item_wide_record_message_is_not_marked_not_inspected() -> None:
    p, ctx = _plugin()

    p.process([{"frame": np.zeros((8, 8, 3), dtype=np.uint8), "detections": []}])

    assert ctx.events[0]["summary"] == "pass: дефектов 0"
    assert "не проверен" not in ctx.events[0]["summary"]
