"""ShmDashboardPanel — панель мониторинга ring-buffer occupancy.

Фаза 6: SHM dashboard.
Read-only панель в правой части конструктора. Показывает все wire-каналы
с их buffer_fill (QProgressBar), fps и latency.

Обновляется из WireDataBridge.metrics_changed.
Dict at Boundary: принимает dict, не WireMetrics напрямую.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _WireMetricsRow(QWidget):
    """Строка для одного wire-канала: имя, progressbar заполненности, fps/latency."""

    def __init__(self, wire_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui(wire_key)

    def _init_ui(self, wire_key: str) -> None:
        """Построить layout строки: имя, progressbar, метрики."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # Метка с именем wire-канала, фиксированная ширина для выравнивания
        self._label_key = QLabel(wire_key, self)
        self._label_key.setFixedWidth(120)
        self._label_key.setToolTip(wire_key)
        layout.addWidget(self._label_key)

        # Progressbar заполненности ring-buffer (0-100%)
        self._progress = QProgressBar(self)
        self._progress.setMinimum(0)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%p%")
        self._progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._progress)

        # Метка с fps и latency
        self._label_metrics = QLabel("0fps, 0.0ms", self)
        self._label_metrics.setFixedWidth(100)
        self._label_metrics.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label_metrics)

    def update(self, fps: float, latency_ms: float, buffer_fill: float) -> None:
        """Обновить отображение метрик для данного wire-канала.

        Args:
            fps: кадров в секунду.
            latency_ms: задержка в миллисекундах.
            buffer_fill: заполненность ring-buffer от 0.0 до 1.0 (clamp до 1.0).
        """
        # Clamp значения заполненности в диапазон [0.0, 1.0]
        fill = max(0.0, min(1.0, buffer_fill))
        percent = int(fill * 100)
        self._progress.setValue(percent)

        # Цвет progressbar зависит от уровня заполненности
        if fill < 0.60:
            # Зелёный — нормальный уровень
            color = "#4caf50"
        elif fill < 0.85:
            # Жёлтый — внимание, заполненность высокая
            color = "#ff9800"
        else:
            # Красный — критический уровень
            color = "#f44336"

        self._progress.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )

        # Обновить текст метрик
        self._label_metrics.setText(f"{fps:.0f}fps, {latency_ms:.1f}ms")


class ShmDashboardPanel(QWidget):
    """Read-only панель мониторинга ring-buffer occupancy всех wire-каналов.

    Отображает строки для каждого wire-канала с:
      - именем канала (QLabel)
      - заполненностью ring-buffer (QProgressBar 0-100%)
      - fps и latency (QLabel)

    Данные принимаются как dict (Dict at Boundary).
    Строки сортируются по wire_key при добавлении.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Словарь строк: wire_key → _WireMetricsRow
        self._rows: dict[str, _WireMetricsRow] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        """Построить layout: заголовок, scroll area со строками, placeholder."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(4)

        # Заголовок панели
        title = QLabel("SHM Dashboard", self)
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        outer_layout.addWidget(title)

        # Scroll area для строк wire-каналов
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Внутренний контейнер со строками
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._rows_layout.addStretch()  # растяжка в конце списка

        self._scroll.setWidget(self._rows_container)
        outer_layout.addWidget(self._scroll)

        # Placeholder — виден когда нет активных wire-каналов
        self._placeholder = QLabel("Нет активных wire-каналов", self)
        self._placeholder.setStyleSheet("color: #888888;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer_layout.addWidget(self._placeholder)

        # Изначально показываем placeholder
        self._scroll.setVisible(False)

    def update_metrics(self, metrics: dict) -> None:
        """Обновить метрики по dict данных.

        Args:
            metrics: словарь вида {wire_key: {"fps": float, "latency_ms": float, "buffer_fill": float}}
                     или {wire_key: WireMetrics} — объект с атрибутами fps, latency_ms, buffer_fill.
                     Dict at Boundary: не импортируем WireMetrics, обращаемся через dict или getattr.
        """
        for wire_key, data in metrics.items():
            # Поддержка dict и объектов с атрибутами (WireMetrics)
            if isinstance(data, dict):
                fps = float(data.get("fps", 0.0))
                latency_ms = float(data.get("latency_ms", 0.0))
                buffer_fill = float(data.get("buffer_fill", 0.0))
            else:
                # Обращаемся через getattr для объектов (не импортируя их тип)
                fps = float(getattr(data, "fps", 0.0))
                latency_ms = float(getattr(data, "latency_ms", 0.0))
                buffer_fill = float(getattr(data, "buffer_fill", 0.0))

            if wire_key in self._rows:
                # Строка уже есть — обновляем значения
                self._rows[wire_key].update(fps, latency_ms, buffer_fill)
            else:
                # Создаём новую строку и вставляем в отсортированную позицию
                row = _WireMetricsRow(wire_key, self._rows_container)
                row.update(fps, latency_ms, buffer_fill)
                self._rows[wire_key] = row

                # Определяем позицию вставки (сортировка по wire_key)
                sorted_keys = sorted(self._rows.keys())
                insert_index = sorted_keys.index(wire_key)

                # Вставляем перед stretch (stretch всегда последний)
                # rows_layout: [row0, row1, ..., stretch]
                # stretch находится по индексу (count - 1)
                self._rows_layout.insertWidget(insert_index, row)

        # Управление видимостью placeholder и scroll area
        has_rows = bool(self._rows)
        self._placeholder.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)

    def clear(self) -> None:
        """Удалить все строки и показать placeholder."""
        # Удаляем все виджеты строк из layout и памяти
        for row in self._rows.values():
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        # Показываем placeholder, скрываем scroll area
        self._placeholder.setVisible(True)
        self._scroll.setVisible(False)


__all__ = ["ShmDashboardPanel"]
