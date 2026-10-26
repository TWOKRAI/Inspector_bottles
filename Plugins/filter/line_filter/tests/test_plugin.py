"""Тесты LineFilterPlugin: configure, режимы, дедуп, overlay."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from Plugins.filter.line_filter.plugin import LineFilterPlugin
from Plugins.filter.line_filter.config import LineFilterConfig
from Plugins.filter.line_filter.registers import LineFilterRegisters


def _make_plugin(**reg_overrides) -> LineFilterPlugin:
    """Плагин, настроенный через configure с локальным register (registers=None)."""
    plugin = LineFilterPlugin()
    ctx = MagicMock()
    ctx.registers = None  # форсим локальный register_class()
    ctx.config = reg_overrides
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    plugin.configure(ctx)
    return plugin


def _dets(*centers) -> dict:
    return {"detections": [{"center": [x, y]} for x, y in centers], "seq_id": 1}


class TestConfig:
    def test_defaults(self):
        cfg = LineFilterConfig()
        assert "LineFilterPlugin" in cfg.plugin_class

    def test_hysteresis_invariant_enforced(self):
        """hysteresis_margin < dedup_radius отвергается валидатором."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="hysteresis_margin"):
            LineFilterRegisters(dedup_radius=10, hysteresis_margin=3)


class TestEnterZone:
    def test_count_after_min_hits(self):
        """Объект в зоне засчитывается после min_hits, один раз."""
        p = _make_plugin(center_x=320, center_y=240, angle=0, zone_width=40, min_hits=2, mode="enter_zone")
        # angle=0 → зона |y-240|<=20. Точка y=240 в зоне.
        p.process([_dets((100, 240))])  # hits=1, не подтверждён
        assert p._counted_total == 0
        p.process([_dets((100, 240))])  # hits=2 → зачёт
        assert p._counted_total == 1
        p.process([_dets((100, 240))])  # armed=False → не дубль
        assert p._counted_total == 1

    def test_single_flash_not_counted(self):
        """Одиночная вспышка (1 кадр) не проходит min_hits."""
        p = _make_plugin(center_y=240, angle=0, zone_width=40, min_hits=2)
        p.process([_dets((100, 240))])
        assert p._counted_total == 0

    def test_out_of_zone_not_counted(self):
        p = _make_plugin(center_y=240, angle=0, zone_width=40, min_hits=1)
        p.process([_dets((100, 100))])  # y=100, вне зоны
        p.process([_dets((100, 100))])
        assert p._counted_total == 0


class TestCrossLine:
    def test_crossing_counts_with_direction(self):
        """Объект, пересёкший линию (смена знака), засчитывается с направлением."""
        p = _make_plugin(
            center_x=320, center_y=240, angle=0, zone_width=10, min_hits=2, max_match_distance=20, mode="cross_line"
        )
        # Плавное движение через y=240 шагами ≤20px (для ассоциации трека).
        for y in (200, 215, 230):
            p.process([_dets((320, y))])
        assert p._counted_total == 0  # ещё не пересёк
        out = p.process([_dets((320, 250))])  # знак сменился → зачёт
        assert p._counted_total == 1
        assert out[0]["filtered"][0]["direction"] == "enter"


class TestOverlayAndOutput:
    def test_overlay_always_has_line(self):
        """overlay содержит vline даже без сработавших точек (с 1-го кадра)."""
        p = _make_plugin(center_x=320, center_y=240, angle=30, zone_width=50)
        out = p.process([{"detections": [], "seq_id": 7}])
        ov = out[0]["overlay"]
        assert len(ov["vlines"]) == 1
        assert ov["vlines"][0]["cx"] == 320
        assert ov["vlines"][0]["angle"] == 30
        assert ov["points"] == []

    def test_output_tagged_and_seq_inherited(self):
        """Выход помечен data_type=overlay и наследует seq_id (для Join)."""
        p = _make_plugin()
        out = p.process([{"detections": [], "seq_id": 42}])
        assert out[0]["data_type"] == "overlay"
        assert out[0]["seq_id"] == 42
        assert "frame" not in out[0]  # кадр не трогаем

    def test_dedup_radius_skips_nearby(self):
        """Новый трек рядом с недавно зачтённым (±dedup) не считается дважды."""
        p = _make_plugin(center_y=240, angle=0, zone_width=40, min_hits=1, dedup_radius=5, max_match_distance=3)
        # min_hits=1 → засчёт сразу. max_match_distance=3 → второй (далёкий по треку,
        # но близкий по дедупу) объект получит новый трек, но дедуп его отсечёт.
        p.process([_dets((100, 240))])
        assert p._counted_total == 1
        p.process([_dets((104, 240))])  # новый трек (>3px от старого), но дедуп ≤5px
        assert p._counted_total == 1


_EMPTY = {"detections": [], "seq_id": 1}


def _armed_zone_edge(**reg_overrides) -> LineFilterPlugin:
    """zone_edge-плагин с горизонтальной линией y=240, взведённый пустыми кадрами (О1: защёлка при старте закрыта)."""
    cfg = {"center_y": 240, "angle": 0, "zone_width": 40, "mode": "zone_edge", **reg_overrides}
    p = _make_plugin(**cfg)
    for _ in range(max(1, p._reg.rearm_frames)):
        p.process([_EMPTY])
    return p


class TestZoneEdge:
    """zone_edge — rising-edge по занятости зоны: одно событие на проход диска.

    Геометрия: angle=0 -> линия горизонтальна, зона |y - 240| <= 20 при zone_width=40; диск
    едет поперёк линии, т.е. по y. Защёлка при старте закрыта (О1, C-42): тестам нужен пустой старт.
    """

    def test_fires_on_first_frame_in_zone(self):
        """После rearm_frames пустых кадров засчитывает с ПЕРВОГО кадра в зоне — без min_hits/трекинга."""
        p = _armed_zone_edge()
        out = p.process([_dets((100, 225))])  # круг сразу в зоне
        assert p._counted_total == 1
        assert out[0]["filtered"][0]["xy"] == [100.0, 225.0]

    def test_start_with_occupied_zone_not_counted(self):
        """О1: плагин стартовал при занятой зоне — первый кадр не засчитывается, взвод по пустым кадрам."""
        p = _make_plugin(center_y=240, angle=0, zone_width=40, rearm_frames=2, mode="zone_edge")
        p.process([_dets((100, 225))])
        assert p._counted_total == 0
        p.process([_EMPTY])
        p.process([_dets((100, 225))])  # 1 пустой кадр < rearm_frames: защёлка ещё закрыта
        assert p._counted_total == 0

    def test_robust_to_large_jumps(self):
        """Диск едет поперёк линии большими скачками (быстрая лента, 30 px/кадр при зоне 40 px) —
        каждый проход засчитывается ровно один раз, ассоциация соседних кадров не нужна."""
        p = _armed_zone_edge(rearm_frames=1, max_match_distance=20)
        p.process([_dets((100, 225))])  # вошёл с верхнего края скачком -> зачёт
        assert p._counted_total == 1
        p.process([_dets((100, 255))])  # ещё в зоне (скачок 30 px) -> не дубль
        assert p._counted_total == 1
        p.process([_dets((100, 285))])  # вышел через нижний край -> пере-взвод (rearm_frames=1)
        p.process([_dets((100, 225))])  # новый диск входит с верхнего края: 30 px от места выхода > 20
        assert p._counted_total == 2

    def test_no_retrigger_while_occupied(self):
        """Пока зона занята — один триггер (rising-edge), без повторов каждый кадр."""
        p = _armed_zone_edge()
        for _ in range(5):
            p.process([_dets((100, 240))])
        assert p._counted_total == 1

    def test_rearm_after_empty_streak(self):
        """Пере-взвод только после rearm_frames пустых кадров (гасит мерцание детекции);
        новый проход входит с другого края зоны, чем вышел прежний."""
        p = _armed_zone_edge(rearm_frames=3, max_match_distance=20)
        p.process([_dets((100, 225))])
        assert p._counted_total == 1
        p.process([_EMPTY])  # 1 пустой кадр < rearm -> НЕ пере-взводим (мерцание)
        p.process([_dets((100, 225))])  # вернулся — зона ещё «занята»
        assert p._counted_total == 1  # не дубль
        p.process([_dets((100, 255))])  # диск дошёл до нижнего края зоны
        for _ in range(3):  # полное освобождение зоны
            p.process([_EMPTY])
        p.process([_dets((100, 225))])  # новый проход с верхнего края (30 px от места выхода > 20)
        assert p._counted_total == 2

    # --- Тесты автора: порядок внутри кадра и побочные эффекты ветки «тот же объект» (C-42) ---

    def test_reacquire_check_uses_previous_last_seen_not_this_frames(self):
        """Внутри одного кадра сравнение идёт с _last_seen ПРЕЖНИХ кадров, а не с тем, что записан
        этим же кадром: иначе вторая точка кадра «совпала» бы с первой."""
        # zone_width=200 -> зона |y - 240| <= 100; радиус ассоциации 20 px.
        p = _armed_zone_edge(zone_width=200, max_match_distance=20)
        p.process([_dets((100, 330))])  # событие 1; _last_seen = (100, 330)
        for _ in range(2):
            p.process([_EMPTY])  # защёлка снята
        # Обе точки далеко (>= 80 px) от места пропажи, но вторая в 11 px от первой (ближней к линии).
        out = p.process([_dets((100, 245), (110, 250))])
        assert p._counted_total == 3
        assert [e["xy"] for e in out[0]["filtered"]] == [[100.0, 245.0], [110.0, 250.0]]

    def test_second_point_matched_against_old_position_only(self):
        """Первая точка кадра — тот же объект (в радиусе прежнего места), вторая в радиусе первой,
        но не прежнего места -> она новая: цепочки «точка через точку» нет."""
        p = _armed_zone_edge(zone_width=200, max_match_distance=20)
        p.process([_dets((100, 250))])  # событие 1; _last_seen = (100, 250)
        for _ in range(2):
            p.process([_EMPTY])
        # (100, 265): 15 px от прежнего места -> тот же объект; (100, 285): 35 px от прежнего места -> новый.
        out = p.process([_dets((100, 265), (100, 285))])
        assert p._counted_total == 2
        assert [e["xy"] for e in out[0]["filtered"]] == [[100.0, 285.0]]

    def test_last_seen_refreshed_on_every_frame_under_latch(self):
        """_last_seen обновляется на КАЖДОМ кадре с точкой в зоне (и под защёлкой): потеря в конце
        длинного прохода — всё ещё тот же объект, хотя с rising edge прошло больше max_age кадров."""
        p = _armed_zone_edge(zone_width=200, max_age=5, max_match_distance=60)
        for i in range(13):  # 13 кадров в зоне, шаг 10 px: y = 150 … 270; с rising edge прошло 12 > max_age
            p.process([_dets((100, 150 + 10 * i))])
        assert p._counted_total == 1
        for _ in range(3):  # потеря 3 кадра: rearm_frames=2 <= 3 <= max_age=5, защёлка снята
            p.process([_EMPTY])
        out = p.process([_dets((100, 310))])  # 40 px от места пропажи (270) <= 60
        assert p._counted_total == 1
        assert out[0]["filtered"] == []

    def test_suppressed_branch_leaves_counters_and_history_untouched(self):
        """Ветка «тот же объект» не трогает _counted_total, _accumulated, _recent и filtered."""
        p = _armed_zone_edge(zone_width=200, max_match_distance=60)
        p.process([_dets((100, 250))])
        for _ in range(2):
            p.process([_EMPTY])
        total, acc, recent = p._counted_total, list(p._accumulated), list(p._recent)
        out = p.process([_dets((100, 280))])  # 30 px от места пропажи, пропуск 2 кадра -> тот же объект
        assert p._counted_total == total == 1
        assert p._accumulated == acc
        assert p._recent == recent
        assert out[0]["filtered"] == []
        assert out[0]["counted_total"] == 1
        assert out[0]["overlay"]["points"] == []

    def test_accumulated_mode_keeps_single_entry_after_reacquire(self):
        """emit_mode=accumulated: после повторного появления того же диска в списке по-прежнему одна запись."""
        p = _armed_zone_edge(zone_width=200, max_match_distance=60, emit_mode="accumulated")
        p.process([_dets((100, 250))])
        for _ in range(2):
            p.process([_EMPTY])
        out = p.process([_dets((100, 280))])
        assert len(out[0]["filtered"]) == 1
        assert out[0]["filtered"][0]["xy"] == [100.0, 250.0]
        assert out[0]["counted_total"] == 1
