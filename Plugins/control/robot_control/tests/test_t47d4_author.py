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
