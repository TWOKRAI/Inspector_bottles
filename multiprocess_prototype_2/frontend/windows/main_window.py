"""MainWindow — главное окно: AppHeader + ImagePanel-placeholder + TabWidget + StatusBar."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.chrome.app_header import AppHeaderWidget
from .config import MainWindowConfig


class MainWindow(QMainWindow):
    """Главное окно Inspector v2.

    Layout (сверху вниз):
      1. AppHeaderWidget  — бренд + статус  (фиксированная высота 60 px)
      2. ImagePanel placeholder (stretch=1) — заменяется через set_image_panel()
      3. QTabWidget        — вкладки управления
    StatusBar: fps + latency.
    """

    def __init__(self, config: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Парсинг конфига (dict at boundary → Pydantic внутри)
        cfg = MainWindowConfig(**(config or {}))
        self.setWindowTitle(cfg.window.title)
        self.setMinimumSize(cfg.window.min_width, cfg.window.min_height)
        self.resize(cfg.window.min_width, cfg.window.min_height)

        # Центральный виджет с вертикальным layout
        central = QWidget()
        self.setCentralWidget(central)
        self._layout = QVBoxLayout(central)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # 1. Header (фиксированная высота)
        self._header = AppHeaderWidget()
        self._header.setFixedHeight(60)
        self._layout.addWidget(self._header)

        # 2. Image panel placeholder — будет заменён реальным ImagePanel
        self._image_panel_placeholder = QWidget()
        self._image_panel_placeholder.setObjectName("ImagePanelPlaceholder")
        self._image_panel_placeholder.setMinimumHeight(200)
        self._layout.addWidget(self._image_panel_placeholder, stretch=1)
        self._image_panel: QWidget | None = None

        # 3. TabWidget
        self._tab_widget = QTabWidget()
        self._layout.addWidget(self._tab_widget)

        # StatusBar
        self._fps_label = QLabel("FPS: --")
        self._latency_label = QLabel("Latency: -- ms")
        self.statusBar().addPermanentWidget(self._fps_label)
        self.statusBar().addPermanentWidget(self._latency_label)

        # Счётчик кадров для расчёта FPS
        self._frame_count = 0

    # -- Properties --

    @property
    def header(self) -> AppHeaderWidget:
        """Виджет заголовка (AppHeaderWidget)."""
        return self._header

    @property
    def tab_widget(self) -> QTabWidget:
        """Виджет вкладок."""
        return self._tab_widget

    # -- Image panel --

    def set_image_panel(self, widget: QWidget) -> None:
        """Заменить placeholder реальным ImagePanel.

        Новый виджет встраивается на то же место в layout (stretch=1).
        """
        idx = self._layout.indexOf(self._image_panel_placeholder)
        self._layout.removeWidget(self._image_panel_placeholder)
        self._image_panel_placeholder.deleteLater()
        self._layout.insertWidget(idx, widget, stretch=1)
        self._image_panel = widget

    # -- Обратная совместимость (старый API) --

    def add_tab(self, widget: QWidget, title: str) -> int:
        """Добавить таб. Возвращает индекс вкладки."""
        return self._tab_widget.addTab(widget, title)

    def update_status(self, fps: float, latency_ms: float = 0.0) -> None:
        """Обновить StatusBar: fps и latency."""
        self._fps_label.setText(f"FPS: {fps:.1f}")
        self._latency_label.setText(f"Latency: {latency_ms:.1f} ms")

    def increment_frame_count(self) -> None:
        """Инкремент счётчика кадров (вызывается при каждом frame)."""
        self._frame_count += 1

    def reset_frame_count(self) -> int:
        """Сбросить счётчик и вернуть значение (для расчёта fps раз в секунду)."""
        count = self._frame_count
        self._frame_count = 0
        return count
