# -*- coding: utf-8 -*-
"""Шаблонная секция управления телеметрией процесса (telemetry-publish-control Ф4.1).

Конструкторный принцип: контролы НЕ хардкодятся per-метрика, а **строятся по шаблону
из списка метрик** (`metrics` — обычно framework `GATED_METRICS`). Одна строка на метрику:

    [✓ вкл]  <метка>   [частота, с ▾]   <эфф. значение / ⚠ потолок>

Добавили метрику в `GATED_METRICS` — строка появилась автоматически, без правки UI.
Секция ничего не знает о транспорте: на изменение зовёт колбэк ``on_change(metric,
enabled, interval_sec)`` (одно из значений — актуальное, другое ``None`` = «не менялось»).
Запись команды и разбор результата (``capped_by_throttle``) — на стороне владельца
(панель через command-result-bridge, presenter строит конверт).

Чтение статуса — из read-model: :meth:`update_readouts` тянет process-level значения
(``processes.<P>.state.<metric>``) из :class:`TelemetryViewModel` и показывает их в строке.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel

# Колбэк изменения: (metric, enabled|None, interval_sec|None). ``None`` = «не менялось»
# на этой оси (тумблер дёрнули — enabled задан, интервал None; и наоборот).
ChangeCallback = Callable[[str, Optional[bool], Optional[float]], None]

# Границы поля частоты: минимум ~20 Гц (0.05с — мягкий дефолт IPC-страховки, ADR-PM-017),
# максимум 60с. Шаг 0.05с. Значение — минимальный интервал публикации метрики.
_INTERVAL_MIN = 0.05
_INTERVAL_MAX = 60.0
_INTERVAL_STEP = 0.05


class _MetricRow:
    """Виджеты одной строки метрики (чекбокс + метка + частота + читаемый статус)."""

    __slots__ = ("metric", "enable", "interval", "readout")

    def __init__(self, metric: str, enable: QCheckBox, interval: QDoubleSpinBox, readout: QLabel) -> None:
        self.metric = metric
        self.enable = enable
        self.interval = interval
        self.readout = readout


class TelemetryControlsSection(QGroupBox):
    """Секция «Телеметрия» — авто-строки контролов по списку метрик.

    Args:
        process_name: имя процесса-адресата (для read-model путей и подписи).
        metrics: список метрик — шаблон строк (обычно framework ``GATED_METRICS``).
        labels: {метрика: русская метка} (отсутствует → сам ключ метрики).
        defaults: {метрика: дефолтный interval_sec} (отсутствует → ``_DEFAULT_INTERVAL``).
        on_change: колбэк изменения (запись делает владелец, не секция).
        parent: Qt-родитель.
    """

    _DEFAULT_INTERVAL = 1.0

    def __init__(
        self,
        process_name: str,
        metrics: list[str],
        *,
        labels: Optional[dict[str, str]] = None,
        defaults: Optional[dict[str, float]] = None,
        on_change: Optional[ChangeCallback] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Телеметрия", parent)
        self._process_name = process_name
        self._labels = labels or {}
        self._defaults = defaults or {}
        self._on_change = on_change
        # Гвард: программное выставление значений (update_readouts) не должно
        # порождать команды записи (как blockSignals, но явно и локально).
        self._suppress = False
        self._rows: dict[str, _MetricRow] = {}

        grid = QGridLayout(self)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(3, 1)  # столбец статуса тянется

        # Шапка (компактная) — читаемость сетки.
        for col, title in enumerate(("Вкл", "Метрика", "Частота, с", "Статус")):
            header = QLabel(title)
            header.setStyleSheet("color: gray; font-size: 11px;")
            grid.addWidget(header, 0, col)

        # ГЛАВНОЕ: строки строятся В ЦИКЛЕ по списку метрик — не хардкод.
        for r, metric in enumerate(metrics, start=1):
            self._build_row(grid, r, metric)

    # ------------------------------------------------------------------ #
    #  Build (шаблон одной строки)                                        #
    # ------------------------------------------------------------------ #

    def _build_row(self, grid: QGridLayout, row: int, metric: str) -> None:
        enable = QCheckBox()
        enable.setChecked(True)  # по умолчанию метрика включена (боевой дефолт gate)
        enable.setToolTip(f"Публиковать метрику «{metric}»")
        enable.toggled.connect(lambda checked, m=metric: self._emit_enabled(m, checked))

        label = QLabel(self._labels.get(metric, metric))

        interval = QDoubleSpinBox()
        interval.setRange(_INTERVAL_MIN, _INTERVAL_MAX)
        interval.setSingleStep(_INTERVAL_STEP)
        interval.setDecimals(2)
        interval.setValue(self._defaults.get(metric, self._DEFAULT_INTERVAL))
        interval.setToolTip("Минимальный интервал публикации (с). Меньше — чаще.")
        # editingFinished — коммитим по завершению ввода, не на каждый шаг спина.
        interval.editingFinished.connect(lambda m=metric: self._emit_interval(m))

        readout = QLabel("—")
        readout.setStyleSheet("color: gray;")
        readout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        grid.addWidget(enable, row, 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(label, row, 1)
        grid.addWidget(interval, row, 2)
        grid.addWidget(readout, row, 3)

        self._rows[metric] = _MetricRow(metric, enable, interval, readout)

    # ------------------------------------------------------------------ #
    #  Emit (изменения пользователя → колбэк владельца)                   #
    # ------------------------------------------------------------------ #

    def _emit_enabled(self, metric: str, checked: bool) -> None:
        if self._suppress or self._on_change is None:
            return
        # Выключенную метрику визуально гасим: поле частоты неактивно.
        self._rows[metric].interval.setEnabled(checked)
        self._on_change(metric, checked, None)

    def _emit_interval(self, metric: str) -> None:
        if self._suppress or self._on_change is None:
            return
        self._on_change(metric, None, float(self._rows[metric].interval.value()))

    # ------------------------------------------------------------------ #
    #  Read-model + результат записи                                      #
    # ------------------------------------------------------------------ #

    def update_readouts(self, telemetry: "TelemetryViewModel | None") -> None:
        """Обновить читаемый статус строк из read-model (process-level значения).

        Тянет ``processes.<P>.state.<metric>`` — доступно для агрегатных fps/latency_ms;
        остальные метрики (per-worker) остаются с эхом настройки. Каппинг-предупреждение,
        выставленное :meth:`show_result`, НЕ затирается (приоритет у явного потолка).
        """
        if telemetry is None:
            return
        for metric, row in self._rows.items():
            # Не перетираем активное caps-предупреждение (оно важнее живого значения).
            if row.readout.property("capped"):
                continue
            value = telemetry.get(f"processes.{self._process_name}.state.{metric}")
            row.readout.setText("—" if value is None else str(value))

    def show_result(self, metric: str, result: dict[str, Any]) -> None:
        """Показать результат записи метрики (command-result-bridge).

        ``capped_by_throttle`` (ADR-PM-017 / Task 1.4) → строка получает видимое
        предупреждение о потолке частоты: «no silent caps» доведено до пользователя.
        Успех без потолка — тихо очищаем прежнее предупреждение.
        """
        row = self._rows.get(metric)
        if row is None:
            return
        caps = _extract_caps(result).get(metric)
        if caps:
            throttle_sec = caps.get("throttle_interval_sec")
            row.readout.setText(f"⚠ троттл {throttle_sec} с")
            row.readout.setStyleSheet("color: #c8860a;")  # янтарный — не ошибка, потолок
            row.readout.setToolTip(
                "Центральный троттл строже запрошенной частоты — частота срезается. "
                "Ослабь central-правило (plane=throttle) или подними интервал."
            )
            row.readout.setProperty("capped", True)
        else:
            row.readout.setStyleSheet("color: gray;")
            row.readout.setToolTip("")
            row.readout.setProperty("capped", False)


def _extract_caps(result: Any) -> dict[str, dict[str, Any]]:
    """Достать ``capped_by_throttle`` из ответа команды (робастно к вложенности).

    Ответ ``telemetry.broadcast`` — ``{..., "publish": {..., "capped_by_throttle":
    {metric: {...}}}}`` — может приехать завёрнутым в ``result`` (одна-две вложенности,
    как в backend_ctl ``_leaf_result``). Спускаемся до узла с ``publish``.
    """
    node = result
    for _ in range(4):
        if not isinstance(node, dict):
            break
        publish = node.get("publish")
        if isinstance(publish, dict) and "capped_by_throttle" in publish:
            caps = publish["capped_by_throttle"]
            return caps if isinstance(caps, dict) else {}
        node = node.get("result")
    return {}


__all__ = ["TelemetryControlsSection", "ChangeCallback"]
