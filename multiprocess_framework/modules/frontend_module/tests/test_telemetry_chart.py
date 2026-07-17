# -*- coding: utf-8 -*-
"""Тесты TelemetryChart (telemetry-dashboard Ф1) — конструкторный многосерийный график.

Инвариант: кривые + легенда строятся ПО СПИСКУ серий (не хардкод). Плюс: точечное
обновление серии, скрытие/показ (легенда-тумблер), compact-режим, graceful на битых точках.
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.widgets.telemetry_chart import (
    SeriesSpec,
    TelemetryChart,
)


def _specs(*keys: str) -> list[SeriesSpec]:
    return [SeriesSpec(key=k, label=k.upper()) for k in keys]


class TestTemplateGeneration:
    def test_one_curve_and_legend_per_series(self, qtbot) -> None:
        chart = TelemetryChart(_specs("camera_0", "camera_1", "detector"))
        qtbot.addWidget(chart)
        assert chart.series_keys() == ["camera_0", "camera_1", "detector"]
        assert set(chart._curves) == {"camera_0", "camera_1", "detector"}
        assert set(chart._checks) == {"camera_0", "camera_1", "detector"}

    def test_arbitrary_series_list_drives_curves(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b", "c", "d", "e"))
        qtbot.addWidget(chart)
        assert len(chart._curves) == 5

    def test_label_falls_back_to_key(self, qtbot) -> None:
        chart = TelemetryChart([SeriesSpec(key="fps")])
        qtbot.addWidget(chart)
        assert chart._specs[0].display_label() == "fps"

    def test_explicit_color_respected(self, qtbot) -> None:
        chart = TelemetryChart([SeriesSpec(key="x", color="#123456")])
        qtbot.addWidget(chart)
        # Кривая создана с заданным пером — цвет применён (проверяем через чекбокс-стиль).
        assert "#123456" in chart._checks["x"].styleSheet()


class TestSeriesData:
    def test_set_series_data_updates_only_target(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"))
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 10.0), (2.0, 20.0)])
        xa, ya = chart._curves["a"].getData()
        xb, yb = chart._curves["b"].getData()
        assert list(ya) == [10.0, 20.0]
        # Серия b не тронута (пустая).
        assert yb is None or len(yb) == 0

    def test_non_numeric_points_dropped(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 5.0), (2.0, None), (3.0, "x"), (4.0, True), (5.0, 7.0)])
        _xs, ys = chart._curves["a"].getData()
        assert list(ys) == [5.0, 7.0]  # None/str/bool отброшены

    def test_unknown_series_key_is_noop(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_series_data("nope", [(1.0, 1.0)])  # не падает

    def test_clear_series(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 1.0), (2.0, 2.0)])
        chart.clear_series("a")
        _xs, ys = chart._curves["a"].getData()
        assert ys is None or len(ys) == 0


class TestVisibility:
    def test_set_visible_hides_curve_and_syncs_checkbox(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"))
        qtbot.addWidget(chart)
        assert chart.is_series_visible("a") is True
        chart.set_visible("a", False)
        assert chart.is_series_visible("a") is False
        assert chart._checks["a"].isChecked() is False  # чекбокс синхронизирован
        # Серия b не затронута.
        assert chart.is_series_visible("b") is True

    def test_legend_checkbox_toggles_curve(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart._checks["a"].setChecked(False)  # клик по легенде
        assert chart.is_series_visible("a") is False

    def test_re_show_series(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_visible("a", False)
        chart.set_visible("a", True)
        assert chart.is_series_visible("a") is True
        assert chart._checks["a"].isChecked() is True


class TestLegendParam:
    def test_legend_false_no_checkboxes(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"), legend=False)
        qtbot.addWidget(chart)
        assert chart._checks == {}  # легенды нет (одиночная серия / mini)
        assert len(chart._curves) == 1  # кривая есть

    def test_legend_true_by_default(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"))
        qtbot.addWidget(chart)
        assert set(chart._checks) == {"a", "b"}


class TestSeriesPoints:
    def test_series_points_roundtrip(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 10.0), (2.0, 20.0)])
        assert chart.series_points("a") == [(1.0, 10.0), (2.0, 20.0)]

    def test_series_points_unknown_or_empty(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        assert chart.series_points("a") == []  # пусто
        assert chart.series_points("nope") == []  # неизвестный ключ


class TestCompactMode:
    def test_compact_has_no_legend(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"), compact=True)
        qtbot.addWidget(chart)
        assert chart._checks == {}  # легенды-тумблеров нет
        assert len(chart._curves) == 2  # кривые есть

    def test_compact_still_accepts_data(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"), compact=True)
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 1.0), (2.0, 2.0)])
        _xs, ys = chart._curves["a"].getData()
        assert list(ys) == [1.0, 2.0]


class TestGraceful:
    def test_empty_series_list(self, qtbot) -> None:
        chart = TelemetryChart([])
        qtbot.addWidget(chart)
        assert chart.series_keys() == []

    def test_empty_points_no_crash(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_series_data("a", [])  # не падает
        assert chart.is_series_visible("a") is True


class TestCrosshair:
    def test_crosshair_off_by_default(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        assert not hasattr(chart, "_readout")
        assert not hasattr(chart, "_vline")

    def test_values_at_x_nearest_per_series(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"), crosshair=True)
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)])
        chart.set_series_data("b", [(1.0, 100.0), (2.0, 200.0), (3.0, 300.0)])
        rows = chart.values_at_x(2.1)  # ближайшее к x=2.1 → точка ts=2.0
        by_key = {r[0]: r[4] for r in rows}
        assert by_key == {"a": 20.0, "b": 200.0}

    def test_values_at_x_excludes_hidden_series(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"), crosshair=True)
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 10.0)])
        chart.set_series_data("b", [(1.0, 20.0)])
        chart.set_visible("b", False)
        keys = {r[0] for r in chart.values_at_x(1.0)}
        assert keys == {"a"}  # скрытая b не в панели

    def test_values_at_x_excludes_empty_series(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a", "b"), crosshair=True)
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1.0, 10.0)])  # b без данных
        keys = {r[0] for r in chart.values_at_x(1.0)}
        assert keys == {"a"}

    def test_format_readout_has_time_and_values(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"), crosshair=True)
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1_700_000_000.0, 42.0)])
        html = chart._format_readout(1_700_000_000.0)
        assert "42.0" in html
        assert "A" in html  # label (upper из _specs)

    def test_format_readout_empty(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"), crosshair=True)
        qtbot.addWidget(chart)
        assert "нет данных" in chart._format_readout(1.0)

    def test_readout_time_is_cursor_not_series_ts(self, qtbot) -> None:
        """Заголовок-время = позиция курсора x (= линия), НЕ ts ближайшей точки серии
        (иначе при разреженных данных серии время рассинхронизировалось бы с линией)."""
        import time as _t

        chart = TelemetryChart(_specs("a"), crosshair=True)
        qtbot.addWidget(chart)
        chart.set_series_data("a", [(1000.0, 7.0)])  # точка далеко от курсора
        html = chart._format_readout(5000.0)  # курсор в x=5000
        assert _t.strftime("%H:%M:%S", _t.localtime(5000.0)) in html  # время = курсор
        assert _t.strftime("%H:%M:%S", _t.localtime(1000.0)) not in html  # НЕ ts точки
        assert "7.0" in html  # значение — ближайший сэмпл серии


class TestYLabel:
    def test_y_label_set_at_init(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"), y_label="Задержка, мс")
        qtbot.addWidget(chart)
        # Подпись оси применена (не падает; текст в label оси).
        assert "Задержка" in chart._plot.getPlotItem().getAxis("left").labelText

    def test_set_y_label_changes_axis(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"))
        qtbot.addWidget(chart)
        chart.set_y_label("FPS")
        assert "FPS" in chart._plot.getPlotItem().getAxis("left").labelText

    def test_set_y_label_noop_in_compact(self, qtbot) -> None:
        chart = TelemetryChart(_specs("a"), compact=True)
        qtbot.addWidget(chart)
        chart.set_y_label("X")  # compact без оси — не падает
