# -*- coding: utf-8 -*-
"""SystemDashboardSection — системный дашборд телеметрии (telemetry-dashboard Ф2).

Многосерийный live-график на вкладке «Все процессы»: СЕРИЯ НА ПРОЦЕСС, легенда-тумблеры
(скрыть/показать процесс), zoom/pan, переключатель метрики (FPS / задержка). Строится
конструкторно — серии из списка процессов, рендер отдаёт переиспользуемому framework-
компоненту :class:`TelemetryChart`. Данные — из read-model (ring 10 мин
``TelemetryViewModel.history``); app-specific часть (маппинг процесс→серия, метки, метрика)
живёт здесь, generic-график — во framework.

Дашборд — ЧТЕНИЕ: скрыть кривую ≠ выключить публикацию (это делает секция контролов Ф4.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from PySide6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from multiprocess_framework.modules.frontend_module.widgets.telemetry_chart import (
    SeriesSpec,
    TelemetryChart,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel

# Метрики дашборда (process-level агрегаты в дереве: processes.<P>.state.<metric>).
# (ключ метрики, подпись в переключателе).
_DASHBOARD_METRICS: tuple[tuple[str, str], ...] = (
    ("fps", "FPS"),
    ("latency_ms", "Задержка, мс"),
)


class SystemDashboardSection(QGroupBox):
    """Секция «Дашборд телеметрии»: серия на процесс + легенда-тумблеры + метрика.

    Args:
        process_names: список процессов — ШАБЛОН серий (одна серия на процесс).
        telemetry: read-model (``TelemetryViewModel``) — источник ring-истории.
        parent: Qt-родитель.

    Инвариант «свежесть при смене рецепта» (code review, нит #4): список серий
    ФИКСИРУЕТСЯ в конструкторе и сам по себе НЕ следит за сменой набора процессов
    (нет add/remove-series после постройки — упрощение, не баг). Актуальность
    после hot-swap рецепта обеспечивает НЕ этот класс, а владелец —
    ``ProcessesTab``: ``ActivateRecipe`` публикует ``TopologyReplaced``,
    ``ProcessesTab._on_topology_replaced`` сравнивает набор процессов и при
    расхождении зовёт ``_sync_nav()``, которая уничтожает старую
    ``AllProcessesPanel`` (а с ней и старый ``SystemDashboardSection``,
    ``deleteLater``) и лениво пересобирает панель заново — новый экземпляр
    строится уже по АКТУАЛЬНОМУ списку процессов. Если рецепт меняется, но
    набор ИМЁН процессов не меняется — пересборки не будет, но и стейла нет
    (ключи серий = имена процессов совпадают). См.
    ``tests/test_system_dashboard.py::TestDashboardRebuildOnRecipeSwap``.
    """

    def __init__(
        self,
        process_names: Sequence[str],
        telemetry: "TelemetryViewModel | None",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Дашборд телеметрии", parent)
        self._process_names = list(process_names)
        self._telemetry = telemetry
        self._metric = _DASHBOARD_METRICS[0][0]  # fps по умолчанию

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Переключатель метрики (FPS / задержка) — одна ось на график.
        top = QHBoxLayout()
        top.addWidget(QLabel("Метрика:"))
        self._metric_combo = QComboBox()
        for key, label in _DASHBOARD_METRICS:
            self._metric_combo.addItem(label, key)
        self._metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        top.addWidget(self._metric_combo)
        top.addStretch(1)
        layout.addLayout(top)

        # Generic-график: серия на процесс (строится В ЦИКЛЕ из списка процессов).
        # crosshair=True — панель значений всех серий под курсором (читаемость при разном
        # масштабе); y_label — подпись оси под текущую метрику.
        specs = [SeriesSpec(key=name, label=name) for name in self._process_names]
        self._chart = TelemetryChart(
            specs,
            x_window_sec=600.0,
            crosshair=True,
            y_label=self._metric_label(self._metric),
        )
        self.setMinimumHeight(300)
        layout.addWidget(self._chart, stretch=1)

    @staticmethod
    def _metric_label(metric_key: str) -> str:
        """Подпись оси/метрики по ключу (юнит для оси Y)."""
        for key, label in _DASHBOARD_METRICS:
            if key == metric_key:
                return label
        return metric_key

    # ------------------------------------------------------------------ #
    #  Обновление                                                         #
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Перечитать ring-историю каждой серии из read-model (по текущей метрике)."""
        if self._telemetry is None:
            return
        for name in self._process_names:
            points = self._telemetry.history(f"processes.{name}.state.{self._metric}")
            self._chart.set_series_data(name, points)

    def _on_metric_changed(self, _index: int) -> None:
        """Смена метрики в переключателе → сменить подпись оси + перечитать все серии."""
        key = self._metric_combo.currentData()
        if isinstance(key, str):
            self._metric = key
        self._chart.set_y_label(self._metric_label(self._metric))
        self.refresh()

    def current_metric(self) -> str:
        """Текущая метрика дашборда (для тестов/диагностики)."""
        return self._metric


__all__ = ["SystemDashboardSection"]
