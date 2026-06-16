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


class TestZoneEdge:
    """zone_edge — rising-edge по занятости зоны, БЕЗ трекинга (робастно к скорости)."""

    def test_fires_on_first_frame_in_zone(self):
        """Засчитывает с ПЕРВОГО кадра в зоне — без min_hits/трекинга."""
        p = _make_plugin(center_x=320, center_y=240, angle=0, zone_width=40, mode="zone_edge")
        out = p.process([_dets((100, 240))])  # круг сразу в зоне
        assert p._counted_total == 1
        assert out[0]["filtered"][0]["xy"] == [100.0, 240.0]

    def test_robust_to_large_jumps(self):
        """Диск «телепортируется» большими скачками (быстрая лента) — каждый проход
        засчитывается ровно один раз, БЕЗ зависимости от max_match_distance."""
        p = _make_plugin(center_y=240, angle=0, zone_width=40, rearm_frames=1, mode="zone_edge")
        p.process([_dets((10, 240))])  # появился в зоне скачком → зачёт
        assert p._counted_total == 1
        p.process([_dets((30, 240))])  # ещё в зоне → не дубль
        assert p._counted_total == 1
        p.process([_dets((500, 50))])  # ушёл из зоны → пере-взвод (rearm_frames=1)
        p.process([_dets((12, 240))])  # новый проход скачком → зачёт
        assert p._counted_total == 2

    def test_no_retrigger_while_occupied(self):
        """Пока зона занята — один триггер (rising-edge), без повторов каждый кадр."""
        p = _make_plugin(center_y=240, angle=0, zone_width=40, mode="zone_edge")
        for _ in range(5):
            p.process([_dets((100, 240))])
        assert p._counted_total == 1

    def test_rearm_after_empty_streak(self):
        """Пере-взвод только после rearm_frames пустых кадров (гасит мерцание детекции)."""
        empty = {"detections": [], "seq_id": 1}
        p = _make_plugin(center_y=240, angle=0, zone_width=40, rearm_frames=3, mode="zone_edge")
        p.process([_dets((100, 240))])
        assert p._counted_total == 1
        p.process([empty])  # 1 пустой кадр < rearm → НЕ пере-взводим (мерцание)
        p.process([_dets((100, 240))])  # вернулся — зона ещё «занята»
        assert p._counted_total == 1  # не дубль
        for _ in range(3):  # полное освобождение зоны
            p.process([empty])
        p.process([_dets((100, 240))])  # новый проход
        assert p._counted_total == 2
