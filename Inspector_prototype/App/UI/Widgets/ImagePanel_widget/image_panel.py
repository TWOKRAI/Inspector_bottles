# App/UI/Widgets/ImagePanel/image_panel.py
# -*- coding: utf-8 -*-
"""
ImagePanelWidget — центральная панель: изображение + оверлейные чекбоксы + метрики.

Ответственность:
  - Отображение кадров с камеры (QLabel)
  - Оверлейные чекбоксы (слева/справа) — привязаны к RegistersManager
  - PerformanceOverlay (FPS, размер, время обработки) — внутри, поверх изображения

НЕ делает:
  - Не хранит состояние чекбоксов (они в RegistersManager)
  - Не вычисляет FPS (получает готовый из сигналов)
  - Не знает про бизнес-логику камер

Архитектура:
  ImagePanelWidget (QWidget)
    ├── LeftPanel (чекбоксы Draw/Camera)
    ├── CenterPanel (QLabel + PerformanceOverlay поверх)
    │     └── PerformanceOverlay (QWidget)
    │           ├── FPS display
    │           ├── Image size
    │           ├── Processing time
    │           └── Total time
    └── RightPanel (чекбоксы Robot/Processing)
"""

from typing import Optional, List, Any
import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QGraphicsOpacityEffect
)

# Components
from App.UI.Components.checkbox_enhanced import CheckboxControlEnhanced
from App.UI.Widgets.ImagePanel_widget.Performance_overlay import PerformanceOverlay

# Registers (только для чтения метаданных и подписки)
from App.Core.Domain.Registers.manager import RegistersManager
from App.Core.Domain.Registers.models.registers.draw import DrawRegisters
from App.Core.Domain.Registers.models.registers.camera import CameraRegisters
from App.Core.Domain.Registers.models.registers.robot import RobotRegisters
from App.Core.Domain.Registers.models.registers.processing import ProcessingRegisters


class ImagePanelWidget(QWidget):
    """
    Центральная панель: чекбоксы + изображение + метрики.
    
    Сигналы:
        frame_displayed: Кадр отображён (для синхронизации)
        overlay_clicked: Клик по оверлею (имя чекбокса)
    """
    
    frame_displayed = pyqtSignal()
    
    def __init__(
        self,
        registers_manager: RegistersManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self._registers = registers_manager
        
        # Текущие метрики (для отображения, не для логики!)
        self._last_metrics: dict = {}
        
        self._setup_ui()
        self._connect_to_registers()
    
    # ═════════════════════════════════════════════════════════════════
    # UI Construction
    # ═════════════════════════════════════════════════════════════════
    
    def _setup_ui(self) -> None:
        """Сборка UI."""
        
        # Главный layout: горизонтальный (чекбоксы | изображение | чекбоксы)
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)
        
        # Левая панель: чекбоксы оверлея
        root.addLayout(self._build_left_panel())
        
        # Центр: изображение с оверлеем метрик
        root.addLayout(self._build_center_panel(), stretch=1)
        
        # Правая панель: чекбоксы управления
        root.addLayout(self._build_right_panel())
    
    def _build_left_panel(self) -> QVBoxLayout:
        """Чекбоксы оверлея (DrawRegisters + CameraRegisters.record_video)."""
        layout = QVBoxLayout()
        layout.setSpacing(4)
        
        # Чекбоксы привязаны к RegistersManager через CheckboxControlEnhanced
        checkboxes = [
            (DrawRegisters, "draw", "Отображение"),
            (DrawRegisters, "circles", "Круги"),
            (DrawRegisters, "rectangles", "Прямоугольники"),
            (CameraRegisters, "record_video", "Запись видео"),
        ]
        
        for register_class, field_name, label in checkboxes:
            cb = CheckboxControlEnhanced(
                field=(register_class, field_name),
                registers_manager=self._registers,
                label_text=label,
                parent=self,
            )
            layout.addWidget(cb)
        
        layout.addStretch()
        return layout
    
    def _build_center_panel(self) -> QVBoxLayout:
        """QLabel для кадра + PerformanceOverlay поверх."""
        layout = QVBoxLayout()
        layout.addStretch()
        
        # Контейнер для изображения (relative positioning для overlay)
        self._image_container = QWidget()
        self._image_container.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 2px solid #444;
                border-radius: 4px;
            }
        """)
        
        # QLabel внутри контейнера
        container_layout = QVBoxLayout(self._image_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setScaledContents(False)
        self._image_label.setMinimumSize(200, 200)
        
        container_layout.addWidget(self._image_label)
        
        # PerformanceOverlay — поверх контейнера
        self._overlay = PerformanceOverlay(self._image_container)
        # Позиционирование в updateGeometry или showEvent
        
        layout.addWidget(self._image_container, stretch=1)
        layout.addStretch()
        
        return layout
    
    def _build_right_panel(self) -> QVBoxLayout:
        """Чекбоксы управления (Robot + Camera + Processing)."""
        layout = QVBoxLayout()
        layout.setSpacing(4)
        
        checkboxes = [
            (RobotRegisters, "servo_on", "Servo ON"),
            (CameraRegisters, "enabled", "Камера вкл."),
            (CameraRegisters, "enable_main_processing", "Обработка"),
            (ProcessingRegisters, "enable_processing", "Процессинг"),
            (RobotRegisters, "server", "Сервер"),
        ]
        
        for register_class, field_name, label in checkboxes:
            cb = CheckboxControlEnhanced(
                field=(register_class, field_name),
                registers_manager=self._registers,
                label_text=label,
                parent=self,
            )
            layout.addWidget(cb)
        
        layout.addStretch()
        return layout
    
    # ═════════════════════════════════════════════════════════════════
    # Подписка на Registers (для синхронизации UI)
    # ═════════════════════════════════════════════════════════════════
    
    def _connect_to_registers(self) -> None:
        """Подписка на изменения регистров (опционально, для расширенной синхронизации)."""
        # Если нужно реагировать на изменения регистров напрямую
        # (обычно CheckboxControlEnhanced сам подписывается)
        pass
    
    # ═════════════════════════════════════════════════════════════════
    # Публичный API: отображение кадров и метрик
    # ═════════════════════════════════════════════════════════════════
    
    def display_frame(
        self,
        frames: List[np.ndarray],
        metrics: Optional[dict] = None,
    ) -> None:
        """
        Отображение кадра и обновление метрик.
        
        Args:
            frames: Список numpy-массивов (обычно 1 кадр)
            metrics: {
                'fps': float,
                'width': int,
                'height': int,
                'proc_time_ms': float,
                'total_time_ms': float,
            }
        """
        if not frames:
            return
        
        frame = frames[0]
        if frame is None:
            return
        
        # Отображаем кадр
        self._render_frame(frame)
        
        # Обновляем метрики
        if metrics:
            self._overlay.update_metrics(**metrics)
            self._last_metrics = metrics
        
        self.frame_displayed.emit()
    
    def _render_frame(self, frame: np.ndarray) -> None:
        """Конвертация numpy → QPixmap."""
        try:
            if frame.ndim == 2:
                # Grayscale
                h, w = frame.shape
                qt_image = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
            else:
                # RGB/BGR
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            pixmap = QPixmap.fromImage(qt_image)
            
            # Масштабирование с сохранением пропорций
            label_size = self._image_label.size()
            scaled = pixmap.scaled(
                label_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            self._image_label.setPixmap(scaled)
            
        except Exception as e:
            print(f"[ImagePanel] Render error: {e}")
    
    # ═════════════════════════════════════════════════════════════════
    # Слоты от других виджетов (Hikvision и т.д.)
    # ═════════════════════════════════════════════════════════════════
    
    def update_image_size(self, width: int, height: int) -> None:
        """Slot от HikvisionWidget (image_size_detected)."""
        self._overlay.update_image_size(width, height)
    
    def update_camera_params(self, params: dict) -> None:
        """Slot от HikvisionWidget (parameters_changed)."""
        # Пробрасываем в overlay
        fps = params.get('frame_rate')
        if fps is not None:
            self._overlay.update_camera_fps(fps)
        
        # Можно добавить другие параметры камеры
        # exposure = params.get('exposure_time')
        # gain = params.get('gain')
    
    def update_camera_fps(self, fps: float) -> None:
        """Явное обновление FPS (альтернативный интерфейс)."""
        self._overlay.update_camera_fps(fps)
    
    # ═════════════════════════════════════════════════════════════════
    # Events
    # ═════════════════════════════════════════════════════════════════
    
    def resizeEvent(self, event) -> None:
        """Перепозиционирование overlay при изменении размера."""
        super().resizeEvent(event)
        # Overlay остаётся в (10, 10) относительно _image_container
        if hasattr(self, '_overlay'):
            self._overlay.move(10, 10)
    
    def showEvent(self, event) -> None:
        """Инициализация позиции overlay."""
        super().showEvent(event)
        if hasattr(self, '_overlay'):
            self._overlay.move(10, 10)