"""MainWindow — главное окно: AppHeader + ImagePanel-placeholder + TabWidget + StatusBar."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.chrome.app_header import AppHeaderWidget
from ..widgets.chrome.error_banner import ErrorBannerWidget
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

        # 1.5. Баннер ошибок/предупреждений (скрыт по умолчанию)
        self._error_banner = ErrorBannerWidget()
        self._layout.addWidget(self._error_banner)

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
        self._fps_label = QLabel("FPS: —")
        self._latency_label = QLabel("Latency: —")
        self._frames_label = QLabel("Frames: —")
        self.statusBar().addPermanentWidget(self._fps_label)
        self.statusBar().addPermanentWidget(self._latency_label)
        self.statusBar().addPermanentWidget(self._frames_label)

        # Счётчик кадров для расчёта FPS
        self._frame_count = 0

        # ActionBus (Phase 11) — устанавливается через set_action_bus()
        self._action_bus = None

    # -- Properties --

    @property
    def header(self) -> AppHeaderWidget:
        """Виджет заголовка (AppHeaderWidget)."""
        return self._header

    @property
    def tab_widget(self) -> QTabWidget:
        """Виджет вкладок."""
        return self._tab_widget

    @property
    def error_banner(self) -> ErrorBannerWidget:
        """Виджет баннера ошибок/предупреждений."""
        return self._error_banner

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

    # -- ActionBus (Phase 11) --

    def set_action_bus(self, bus: object) -> None:
        """Установить ActionBus и привязать Ctrl+Z / Ctrl+Y shortcuts."""
        self._action_bus = bus

        undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_shortcut.activated.connect(self._on_undo)
        self._undo_shortcut = undo_shortcut  # prevent GC

        redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_shortcut.activated.connect(self._on_redo)
        self._redo_shortcut = redo_shortcut  # prevent GC

    def _on_undo(self) -> None:
        """Отменить последнее действие."""
        if self._action_bus is None:
            return
        action = self._action_bus.undo()
        if action:
            self.statusBar().showMessage(f"Отменено: {action.description}", 3000)

    def _on_redo(self) -> None:
        """Повторить отменённое действие."""
        if self._action_bus is None:
            return
        action = self._action_bus.redo()
        if action:
            self.statusBar().showMessage(f"Повторено: {action.description}", 3000)

    # -- Live bindings (Phase 12) --

    def connect_bindings(self, bindings: object) -> None:
        """Подключить StatusBar к live state_delta через GuiStateBindings.

        Args:
            bindings: GuiStateBindings (принимает object для обратной совместимости).
        """
        if bindings is None or not hasattr(bindings, "bind"):
            return

        bindings.bind(
            "system.fps",
            self._fps_label,
            "text",
            formatter=lambda v: f"FPS: {v:.1f}" if isinstance(v, (int, float)) else "FPS: —",
        )
        bindings.bind(
            "system.latency_ms",
            self._latency_label,
            "text",
            formatter=lambda v: f"Latency: {v:.0f} ms" if isinstance(v, (int, float)) else "Latency: —",
        )
        bindings.bind(
            "system.total_frames",
            self._frames_label,
            "text",
            formatter=lambda v: f"Frames: {v}" if isinstance(v, (int, float)) else "Frames: —",
        )

        # Привязка баннера к системным ошибкам и предупреждениям.
        # Fallback в GuiStateBindings (getattr + callable) вызывает
        # show_error(value) / show_warning(value) напрямую.
        bindings.bind(
            "system.error",
            self._error_banner,
            "show_error",
        )
        bindings.bind(
            "system.warning",
            self._error_banner,
            "show_warning",
        )

    # -- Обратная совместимость (старый API) --

    def add_tab(self, widget: QWidget, title: str) -> int:
        """Добавить таб. Возвращает индекс вкладки."""
        return self._tab_widget.addTab(widget, title)

    def update_status(self, fps: float, latency_ms: float = 0.0) -> None:
        """Обновить StatusBar и header: fps и latency."""
        self._fps_label.setText(f"FPS: {fps:.1f}")
        self._latency_label.setText(f"Latency: {latency_ms:.1f} ms")
        # Дублируем ключевые метрики в header
        self._header.update_status(f"FPS: {fps:.1f} | Latency: {latency_ms:.1f} ms")

    def increment_frame_count(self) -> None:
        """Инкремент счётчика кадров (вызывается при каждом frame)."""
        self._frame_count += 1

    def reset_frame_count(self) -> int:
        """Сбросить счётчик и вернуть значение (для расчёта fps раз в секунду)."""
        count = self._frame_count
        self._frame_count = 0
        return count
