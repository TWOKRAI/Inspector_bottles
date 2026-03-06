

from typing import Optional
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import  QTimer


class PerformanceOverlay(QWidget):
    """
    Плашка с метриками производительности.
    Поверх изображения, полупрозрачная, в углу.
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # Фиксированный размер и позиция (в углу родителя)
        self.setFixedSize(200, 120)
        self.move(10, 10)
        
        # Полупрозрачный фон
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 180);
                border-radius: 8px;
                padding: 8px;
            }
            QLabel {
                color: white;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                background: transparent;
                padding: 1px;
            }
        """)
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        
        # Метрики
        self._fps_label = QLabel("FPS: --")
        self._size_label = QLabel("Size: --×--")
        self._proc_label = QLabel("Process: -- ms")
        self._total_label = QLabel("Total: -- ms")
        
        # Цветовая кодировка
        self._fps_label.setStyleSheet("color: #2ecc71;")      # Зелёный
        self._size_label.setStyleSheet("color: #3498db;")    # Синий
        self._proc_label.setStyleSheet("color: #f39c12;")    # Оранжевый
        self._total_label.setStyleSheet("color: #e74c3c;")   # Красный
        
        layout.addWidget(self._fps_label)
        layout.addWidget(self._size_label)
        layout.addWidget(self._proc_label)
        layout.addWidget(self._total_label)
        
        # По умолчанию скрыта (показываем при первых данных)
        self.hide()
        
        # Таймер автоскрытия если нет данных
        self._hide_timer = QTimer(self)
        self._hide_timer.timeout.connect(self.hide)
        self._hide_timer.setSingleShot(True)
    
    def update_metrics(
        self,
        fps: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        proc_time_ms: Optional[float] = None,
        total_time_ms: Optional[float] = None,
    ) -> None:
        """Обновление метрик."""
        
        if fps is not None:
            self._fps_label.setText(f"FPS: {fps:.1f}")
        
        if width is not None and height is not None:
            self._size_label.setText(f"Size: {width}×{height}")
        
        if proc_time_ms is not None:
            self._proc_label.setText(f"Process: {proc_time_ms:.1f} ms")
        
        if total_time_ms is not None:
            self._total_label.setText(f"Total: {total_time_ms:.1f} ms")
        
        # Показываем если есть данные
        if any(x is not None for x in [fps, width, height, proc_time_ms, total_time_ms]):
            self.show()
            # Скрыть через 5 сек если не обновляется
            self._hide_timer.start(5000)
    
    def update_camera_fps(self, fps: float) -> None:
        """FPS от камеры (SDK)."""
        self._fps_label.setText(f"Cam FPS: {fps:.1f}")
        self.show()
        self._hide_timer.start(5000)
    
    def update_image_size(self, width: int, height: int) -> None:
        """Размер изображения."""
        self._size_label.setText(f"Size: {width}×{height}")
        self.show()