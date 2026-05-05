"""MainWindow — главное окно с QTabWidget и StatusBar."""
from PySide6.QtWidgets import QMainWindow, QTabWidget, QLabel


class MainWindow(QMainWindow):
    """Главное окно с табами. StatusBar: fps + latency."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inspector v2")
        self.resize(1024, 768)

        # Табы
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        # StatusBar
        self._fps_label = QLabel("FPS: --")
        self._latency_label = QLabel("Latency: -- ms")
        self.statusBar().addPermanentWidget(self._fps_label)
        self.statusBar().addPermanentWidget(self._latency_label)

        # Счётчик кадров для расчёта FPS
        self._frame_count = 0

    def add_tab(self, widget, title: str) -> int:
        """Добавить таб. Возвращает индекс вкладки."""
        return self._tabs.addTab(widget, title)

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
