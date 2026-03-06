# -*- coding: utf-8 -*-
"""
ImagePanelWidget — центральная панель: оверлейные чекбоксы слева/справа + кадр камеры.

Структура:
    [ Левые чекбоксы (DrawRegisters) ] | [ QLabel — кадр ] | [ Правые чекбоксы (Camera/Robot) ]

Все чекбоксы привязаны к RegistersManager через CheckboxControlEnhanced.
Никаких controls_* словарей — единственный источник состояния: RegistersManager.

Использование:
    panel = ImagePanelWidget(registers_manager=rm, parent=main_window)
    # ... после получения кадра из UpdateImage thread:
    panel.display_frames([ndarray_frame])
"""
from typing import Any, List, Optional

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from App.Components.checkbox_enhanced import CheckboxControlEnhanced
from App.Registers.models.registers.camera import CameraRegisters
from App.Registers.models.registers.draw import DrawRegisters
from App.Registers.models.registers.processing import ProcessingRegisters
from App.Registers.models.registers.robot import RobotRegisters


class ImagePanelWidget(QWidget):
    """
    Центральная панель главного окна.

    Слева — чекбоксы оверлея (рисование):
        draw, circles, rectangles  → DrawRegisters
        record_video               → CameraRegisters

    В центре — QLabel для отображения кадров с камеры.

    Справа — чекбоксы управления:
        servo_on               → RobotRegisters
        enabled                → CameraRegisters  (камера вкл.)
        enable_main_processing → CameraRegisters  (обработка вкл.)
        enable_processing      → ProcessingRegisters
        server                 → RobotRegisters

    Args:
        registers_manager: Единственный источник состояния всех чекбоксов.
        parent:            Родительский виджет (обычно MainWindow).
    """

    def __init__(
        self,
        registers_manager: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._rm = registers_manager
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        root.addLayout(self._build_left_panel())
        root.addLayout(self._build_center_panel(), stretch=1)
        root.addLayout(self._build_right_panel())

    def _build_left_panel(self) -> QVBoxLayout:
        """Чекбоксы оверлея (DrawRegisters + CameraRegisters.record_video)."""
        layout = QVBoxLayout()
        layout.setSpacing(4)

        for field in (
            (DrawRegisters, "draw"),
            (DrawRegisters, "circles"),
            (DrawRegisters, "rectangles"),
            (CameraRegisters, "record_video"),
        ):
            layout.addWidget(
                CheckboxControlEnhanced(
                    field=field,
                    registers_manager=self._rm,
                    position="top",
                    parent=self,
                )
            )

        layout.addStretch()
        return layout

    def _build_center_panel(self) -> QVBoxLayout:
        """QLabel для кадра камеры, растянут по высоте."""
        layout = QVBoxLayout()
        layout.addStretch()

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet(
            "border: 2px solid white; border-radius: 10px;"
        )
        self.image_label.setMinimumSize(200, 200)
        layout.addWidget(self.image_label)

        layout.addStretch()
        return layout

    def _build_right_panel(self) -> QVBoxLayout:
        """Чекбоксы управления (Camera / Robot / Processing)."""
        layout = QVBoxLayout()
        layout.setSpacing(4)

        for field in (
            (RobotRegisters, "servo_on"),
            (CameraRegisters, "enabled"),
            (CameraRegisters, "enable_main_processing"),
            (ProcessingRegisters, "enable_processing"),
            (RobotRegisters, "server"),
        ):
            layout.addWidget(
                CheckboxControlEnhanced(
                    field=field,
                    registers_manager=self._rm,
                    position="top",
                    parent=self,
                )
            )

        layout.addStretch()
        return layout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display_frames(self, frames: List[Any]) -> None:
        """Отобразить кадры, полученные из UpdateImage.update_frame сигнала.

        Args:
            frames: Список numpy-массивов (первый — основной кадр для отображения).
        """
        if not frames:
            return
        frame = frames[0]
        if frame is None:
            return
        try:
            self._render_frame(frame)
        except Exception:
            pass

    def _render_frame(self, frame: np.ndarray) -> None:
        """Конвертировать ndarray → QPixmap и отобразить в image_label."""
        if frame.ndim == 2:
            h, w = frame.shape
            qt_img = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w, ch = frame.shape
            qt_img = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888)

        pixmap = QPixmap.fromImage(qt_img)
        label_size = self.image_label.size()
        scaled = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
