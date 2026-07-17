# -*- coding: utf-8 -*-
"""TelemetryChart — переиспользуемый многосерийный live-график на PyQtGraph (telemetry-dashboard Ф1).

Конструкторный компонент: строит график по ДЕКЛАРАТИВНОМУ списку серий (``SeriesSpec``) —
как секция Ф4.1 строится по ``GATED_METRICS``. Ничего не знает о конкретных метриках/процессах:
владелец даёт список серий + гонит в него точки (``set_series_data``). Любая вкладка/приложение
получает интерактивный график (легенда-тумблеры скрыть/показать, zoom/pan, downsampling) даром —
framework-first, не импортирует прототип.

PyQtGraph выбран для ЕДИНООБРАЗИЯ (одна система графиков) + array-рендер (numpy) с встроенными
downsampling/clip — тысячи точек и высокая частота не фризят. ``compact``-режим — мини-график
(без легенды/осей) как замена кастом-спарклайну (Ф3).

Границы: виджет — во frontend_module (framework GUI-слой, уже PySide6). Импортирует pyqtgraph
лениво не нужно (модуль GUI и так грузит Qt), но numpy/pyqtgraph — на уровне модуля.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pyqtgraph as pg

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QCheckBox

# Стабильная палитра по индексу серии (серия без явного color берёт цвет по позиции).
# Согласована с палитрой вкладки «Процессы» (#2563eb — основной, #dc2626 — второй).
_DEFAULT_PALETTE: tuple[str, ...] = (
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#d97706",
    "#9333ea",
    "#0891b2",
    "#db2777",
    "#65a30d",
)


@dataclass
class SeriesSpec:
    """Декларативное описание одной серии графика (конструкторный вход).

    ``key`` — стабильный идентификатор (по нему гонятся данные и переключается видимость);
    ``label`` — подпись в легенде (пусто → ``key``); ``color`` — цвет линии (пусто → из палитры
    по индексу); ``y_axis`` — задел на несколько осей (пока не используется, левая ось для всех).
    """

    key: str
    label: str = ""
    color: Optional[str] = None
    y_axis: str = "left"

    def display_label(self) -> str:
        return self.label or self.key


class TelemetryChart(QWidget):
    """Многосерийный live-график: список серий → кривые + легенда-тумблеры + zoom/pan.

    Args:
        series: список :class:`SeriesSpec` — ШАБЛОН серий (кривые строятся В ЦИКЛЕ по нему).
        x_window_sec: ширина окна по времени (задел для скользящего окна; пока auto-range).
        compact: мини-режим (без легенды и осей) — замена кастом-спарклайну (Ф3).
        downsample: включить ``setDownsampling(auto)`` + ``setClipToView`` (дёшево при тысячах точек).
        time_axis: ось X как читаемое время (``DateAxisItem``) — для дашборда; в compact выключено.
        parent: Qt-родитель.
    """

    def __init__(
        self,
        series: Sequence[SeriesSpec],
        *,
        x_window_sec: float = 600.0,
        compact: bool = False,
        downsample: bool = True,
        time_axis: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._specs: list[SeriesSpec] = list(series)
        self._x_window_sec = x_window_sec
        self._compact = compact
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._checks: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        axis_items = {"bottom": pg.DateAxisItem()} if (time_axis and not compact) else None
        self._plot = pg.PlotWidget(axisItems=axis_items)
        pi = self._plot.getPlotItem()
        pi.showGrid(x=True, y=True, alpha=0.2)
        if downsample:
            # peak-downsampling + clip-to-view: тысячи точек рисуются дёшево, zoom не тормозит.
            pi.setDownsampling(mode="peak", auto=True)
            pi.setClipToView(True)
        if compact:
            # Мини-режим (спарклайн-паритет): без осей/кнопок/меню/интерактива.
            pi.hideAxis("bottom")
            pi.hideAxis("left")
            pi.hideButtons()
            pi.setMenuEnabled(False)
            self._plot.setMouseEnabled(x=False, y=False)
            self.setMinimumHeight(56)
        layout.addWidget(self._plot, stretch=1)

        # ГЛАВНОЕ: кривые строятся В ЦИКЛЕ по списку серий — не хардкод.
        for i, spec in enumerate(self._specs):
            color = spec.color or _DEFAULT_PALETTE[i % len(_DEFAULT_PALETTE)]
            curve = pi.plot([], [], pen=pg.mkPen(color, width=1.5), name=spec.display_label())
            self._curves[spec.key] = curve

        # Легенда-тумблеры (свой ряд чекбоксов = кликабельная легенда) — конструкторно,
        # тестируемо. В compact легенды нет (мини-график).
        if not compact:
            self._build_legend(layout)

    # ------------------------------------------------------------------ #
    #  Build                                                              #
    # ------------------------------------------------------------------ #

    def _build_legend(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)
        for i, spec in enumerate(self._specs):
            color = spec.color or _DEFAULT_PALETTE[i % len(_DEFAULT_PALETTE)]
            cb = QCheckBox(spec.display_label())
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {color};")
            cb.setToolTip(f"Показать/скрыть «{spec.display_label()}»")
            cb.toggled.connect(lambda checked, k=spec.key: self.set_visible(k, checked))
            row.addWidget(cb)
            self._checks[spec.key] = cb
        row.addStretch(1)
        layout.addLayout(row)

    # ------------------------------------------------------------------ #
    #  API                                                                #
    # ------------------------------------------------------------------ #

    def set_series_data(self, key: str, points: Sequence[tuple[float, object]]) -> None:
        """Обновить точки ОДНОЙ серии (только числовые value; прочие серии не тронуты)."""
        curve = self._curves.get(key)
        if curve is None:
            return
        xs: list[float] = []
        ys: list[float] = []
        for t, v in points:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                xs.append(float(t))
                ys.append(float(v))
        curve.setData(xs, ys)

    def set_visible(self, key: str, visible: bool) -> None:
        """Скрыть/показать серию (легенда-тумблер зовёт это же). Синхронизирует чекбокс."""
        curve = self._curves.get(key)
        if curve is not None:
            curve.setVisible(bool(visible))
        cb = self._checks.get(key)
        if cb is not None and cb.isChecked() != bool(visible):
            cb.blockSignals(True)
            cb.setChecked(bool(visible))
            cb.blockSignals(False)

    def clear_series(self, key: str) -> None:
        """Очистить точки серии (без удаления самой кривой)."""
        curve = self._curves.get(key)
        if curve is not None:
            curve.setData([], [])

    def series_keys(self) -> list[str]:
        """Ключи серий в порядке объявления (для драйверов/тестов)."""
        return [s.key for s in self._specs]

    def is_series_visible(self, key: str) -> bool:
        """Видима ли серия (для тестов/диагностики)."""
        curve = self._curves.get(key)
        return bool(curve.isVisible()) if curve is not None else False


__all__ = ["TelemetryChart", "SeriesSpec"]
