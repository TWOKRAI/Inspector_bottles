# -*- coding: utf-8 -*-
"""Приёмочные тесты ``TelemetryChart.series_points`` (слепые, по критериям A1-A5).

Контракт (из докстринга метода): ``series_points(key) -> list[tuple[float, float]]`` —
исходные точки серии в порядке добавления (не downsampled-дисплей); неизвестный ключ или
пустая серия -> ``[]``. Авто-даунсэмплинг peak (pyqtgraph 0.14) включён по умолчанию
(``downsample=True``) и не должен влиять на результат.

A1: N точек подано - ровно те же N точек возвращено, в порядке подачи.
A2: A1 при зазорах по x 8e-6 / 1e-3 / 0.1 / 1.0 и при одинаковых x.
A3: A1 при любом диапазоне видимой области (до/после setXRange/setYRange).
A4: пустая серия / неизвестный ключ -> ``[]`` без исключения.
A5: вызов не меняет данные; два вызова подряд равны.
"""

from __future__ import annotations

import pyqtgraph as pg
import pytest

from multiprocess_framework.modules.frontend_module.widgets.telemetry_chart import (
    SeriesSpec,
    TelemetryChart,
)

# Эпоха (wall-clock, как требует контракт time_axis=True) и нулевая база.
_EPOCH = 1_700_000_000.0
_BASES = [0.0, _EPOCH]
_GAPS = [8e-6, 1e-3, 0.1, 1.0, 0.0]


def _make_chart(qtbot, *keys: str) -> TelemetryChart:
    chart = TelemetryChart([SeriesSpec(key=k, label=k.upper()) for k in (keys or ("a",))])
    qtbot.addWidget(chart)
    chart.resize(800, 400)
    chart.show()
    return chart


def _plot_widget(chart: TelemetryChart) -> pg.PlotWidget:
    pw = chart.findChild(pg.PlotWidget)
    assert pw is not None, "в TelemetryChart не найден pg.PlotWidget"
    return pw


def _points(base: float, gap: float, n: int) -> list[tuple[float, float]]:
    # y - различимые литеральные значения (не монотонные, чтобы порядок был виден).
    ys = [5.0, -3.5, 12.25, 0.0, 7.75, -1.0, 100.5, 42.0, -8.0, 3.0]
    return [(base + i * gap, ys[i % len(ys)] + i) for i in range(n)]


class TestA1ExactPoints:
    def test_five_literal_points_returned_in_order(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1.0, 10.0), (2.0, 20.0), (3.0, 15.0), (4.0, -5.0), (5.0, 0.5)])
        assert chart.series_points("a") == [(1.0, 10.0), (2.0, 20.0), (3.0, 15.0), (4.0, -5.0), (5.0, 0.5)]

    def test_returns_list_of_float_pairs(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1.0, 10.0), (2.0, 20.0)])
        got = chart.series_points("a")
        assert isinstance(got, list)
        assert [(type(x), type(y)) for x, y in got] == [(float, float), (float, float)]

    def test_single_point(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1.5, 2.5)])
        assert chart.series_points("a") == [(1.5, 2.5)]

    def test_many_points_not_thinned_by_downsampling(self, qtbot) -> None:
        # 5000 точек >> ширины виджета (800 px): peak-даунсэмплинг активен, но данные - исходные.
        chart = _make_chart(qtbot)
        pts = _points(_EPOCH, 0.5, 5000)
        chart.set_series_data("a", pts)
        assert chart.series_points("a") == pts

    def test_order_of_addition_kept_for_unsorted_y(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        pts = [(1.0, 9.0), (2.0, -9.0), (3.0, 9.0), (4.0, -9.0), (5.0, 0.0)]
        chart.set_series_data("a", pts)
        assert [y for _x, y in chart.series_points("a")] == [9.0, -9.0, 9.0, -9.0, 0.0]

    def test_other_series_not_mixed_in(self, qtbot) -> None:
        chart = _make_chart(qtbot, "a", "b")
        chart.set_series_data("a", [(1.0, 10.0), (2.0, 20.0)])
        chart.set_series_data("b", [(1.0, 111.0)])
        assert chart.series_points("a") == [(1.0, 10.0), (2.0, 20.0)]
        assert chart.series_points("b") == [(1.0, 111.0)]


class TestA2XGaps:
    @pytest.mark.parametrize("base", _BASES, ids=["base0", "epoch"])
    @pytest.mark.parametrize("gap", _GAPS, ids=["8us", "1ms", "0.1s", "1s", "same_x"])
    def test_ten_points_all_returned(self, qtbot, base: float, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = _points(base, gap, 10)
        chart.set_series_data("a", pts)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", _GAPS, ids=["8us", "1ms", "0.1s", "1s", "same_x"])
    def test_result_not_empty(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", _points(_EPOCH, gap, 10))
        assert len(chart.series_points("a")) == 10

    @pytest.mark.parametrize("gap", _GAPS, ids=["8us", "1ms", "0.1s", "1s", "same_x"])
    def test_thousand_points(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = _points(_EPOCH, gap, 1000)
        chart.set_series_data("a", pts)
        assert chart.series_points("a") == pts

    def test_two_points_8_microseconds_literal(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1000.0, 1.0), (1000.000008, 2.0)])
        assert chart.series_points("a") == [(1000.0, 1.0), (1000.000008, 2.0)]

    def test_two_identical_x_literal(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1000.0, 1.0), (1000.0, 2.0)])
        assert chart.series_points("a") == [(1000.0, 1.0), (1000.0, 2.0)]


class TestA3ViewBoxIndependence:
    _N = 20

    def _fed(self, gap: float) -> list[tuple[float, float]]:
        return _points(_EPOCH, gap, self._N)

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_before_any_range_set(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_narrow_x_range_after_feed(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        _plot_widget(chart).setXRange(_EPOCH, _EPOCH + 1e-6, padding=0)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_very_wide_x_range_after_feed(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        _plot_widget(chart).setXRange(-1e12, 1e12, padding=0)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_narrow_y_range_after_feed(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        _plot_widget(chart).setYRange(0.0, 1e-9, padding=0)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_very_wide_y_range_after_feed(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        _plot_widget(chart).setYRange(-1e12, 1e12, padding=0)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_narrow_range_set_before_feed(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pw = _plot_widget(chart)
        pw.setXRange(_EPOCH, _EPOCH + 1e-6, padding=0)
        pw.setYRange(0.0, 1e-9, padding=0)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        assert chart.series_points("a") == pts

    @pytest.mark.parametrize("gap", [8e-6, 1e-3, 1.0], ids=["8us", "1ms", "1s"])
    def test_wide_range_set_before_feed(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        pw = _plot_widget(chart)
        pw.setXRange(-1e12, 1e12, padding=0)
        pw.setYRange(-1e12, 1e12, padding=0)
        pts = self._fed(gap)
        chart.set_series_data("a", pts)
        assert chart.series_points("a") == pts

    def test_range_far_from_data(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(8e-6)
        chart.set_series_data("a", pts)
        _plot_widget(chart).setXRange(0.0, 1.0, padding=0)
        assert chart.series_points("a") == pts

    def test_range_changes_between_calls(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        pts = self._fed(8e-6)
        chart.set_series_data("a", pts)
        pw = _plot_widget(chart)
        pw.setXRange(_EPOCH, _EPOCH + 1e-6, padding=0)
        first = chart.series_points("a")
        pw.setXRange(-1e12, 1e12, padding=0)
        second = chart.series_points("a")
        assert first == pts
        assert second == pts


class TestA4Empty:
    def test_series_never_fed_returns_empty_list(self, qtbot) -> None:
        chart = _make_chart(qtbot, "a", "b")
        assert chart.series_points("a") == []

    def test_unknown_key_returns_empty_list(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        assert chart.series_points("no_such_series") == []

    def test_unknown_key_with_other_series_fed(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1.0, 1.0)])
        assert chart.series_points("zzz") == []

    def test_set_empty_list_returns_empty_list(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [])
        assert chart.series_points("a") == []

    def test_after_clear_series_returns_empty_list(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", [(1.0, 1.0), (2.0, 2.0)])
        chart.clear_series("a")
        assert chart.series_points("a") == []

    def test_empty_result_type_is_list(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        got = chart.series_points("a")
        assert isinstance(got, list)

    def test_empty_with_narrow_range(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        _plot_widget(chart).setXRange(0.0, 1e-9, padding=0)
        assert chart.series_points("a") == []


class TestA5NoSideEffects:
    @pytest.mark.parametrize("gap", [8e-6, 1.0, 0.0], ids=["8us", "1s", "same_x"])
    def test_two_consecutive_calls_equal(self, qtbot, gap: float) -> None:
        chart = _make_chart(qtbot)
        chart.set_series_data("a", _points(_EPOCH, gap, 50))
        first = chart.series_points("a")
        second = chart.series_points("a")
        assert first == second
        assert len(first) == 50

    def test_call_does_not_change_count_and_order(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        pts = _points(_EPOCH, 8e-6, 30)
        chart.set_series_data("a", pts)
        for _ in range(5):
            chart.series_points("a")
        assert chart.series_points("a") == pts

    def test_mutating_returned_list_does_not_change_chart(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        pts = _points(_EPOCH, 1.0, 10)
        chart.set_series_data("a", pts)
        got = chart.series_points("a")
        got.clear()
        assert chart.series_points("a") == pts

    def test_call_on_empty_does_not_create_data(self, qtbot) -> None:
        chart = _make_chart(qtbot)
        chart.series_points("a")
        chart.series_points("a")
        assert chart.series_points("a") == []

    def test_call_does_not_touch_other_series(self, qtbot) -> None:
        chart = _make_chart(qtbot, "a", "b")
        chart.set_series_data("a", [(1.0, 1.0), (2.0, 2.0)])
        chart.set_series_data("b", [(5.0, 50.0)])
        chart.series_points("a")
        chart.series_points("zzz")
        assert chart.series_points("b") == [(5.0, 50.0)]
