"""MainWindow — primary application window (simplified for v3)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import numpy as np

try:
    from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage, QPixmap
except ImportError:
    QMainWindow = object


class MainWindow(QMainWindow):
    """Simplified main window with camera view and basic controls.

    TODO: Migrate full widget set from v2 (processing, regions, recipes tabs).
    Currently provides: camera display + start/stop + basic status.
    """

    def __init__(
        self,
        config: Dict[str, Any] = None,
        registers_manager: Any = None,
        camera_callbacks_map: Dict[str, Callable] = None,
        camera_type: str = "simulator",
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self._config = config or {}
        self._registers = registers_manager
        self._callbacks = camera_callbacks_map or {}
        self._camera_type = camera_type

        window_cfg = self._config.get("window", {})
        self.setWindowTitle(window_cfg.get("title", "Inspector Prototype v3"))
        self.setMinimumSize(
            window_cfg.get("width", 1024),
            window_cfg.get("height", 600),
        )
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Camera display
        self._frame_label = QLabel("No frame")
        self._frame_label.setAlignment(Qt.AlignCenter)
        self._frame_label.setMinimumSize(640, 480)
        self._frame_label.setStyleSheet("background-color: #1a1a2e; color: white;")

        # Mask display
        self._mask_label = QLabel("No mask")
        self._mask_label.setAlignment(Qt.AlignCenter)
        self._mask_label.setMinimumSize(320, 240)
        self._mask_label.setStyleSheet("background-color: #16213e; color: white;")

        display_layout = QHBoxLayout()
        display_layout.addWidget(self._frame_label, stretch=2)
        display_layout.addWidget(self._mask_label, stretch=1)
        layout.addLayout(display_layout)

        # Controls
        controls = QHBoxLayout()
        self._btn_start = QPushButton("Start Capture")
        self._btn_stop = QPushButton("Stop Capture")
        self._status_label = QLabel("Ready")

        self._btn_start.clicked.connect(lambda: self._callbacks.get("start_capture", lambda: None)())
        self._btn_stop.clicked.connect(lambda: self._callbacks.get("stop_capture", lambda: None)())

        controls.addWidget(self._btn_start)
        controls.addWidget(self._btn_stop)
        controls.addWidget(self._status_label)
        controls.addStretch()
        layout.addLayout(controls)

        # FPS label
        self._fps_label = QLabel("FPS: 0")
        layout.addWidget(self._fps_label)

    def update_frame(
        self,
        original_frame: np.ndarray,
        mask_frame: np.ndarray,
        frame_id: int,
        show_original: bool = True,
        show_mask: bool = True,
    ):
        """Update camera and mask displays."""
        if show_original and original_frame is not None:
            self._display_frame(self._frame_label, original_frame)
        if show_mask and mask_frame is not None:
            self._display_frame(self._mask_label, mask_frame)

    def _display_frame(self, label: QLabel, frame: np.ndarray):
        """Convert numpy frame to QPixmap and display."""
        try:
            h, w = frame.shape[:2]
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                bytes_per_line = 3 * w
                qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            else:
                qimg = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(scaled)
        except Exception:
            pass

    def update_camera_status(self, text: str):
        self._status_label.setText(text)

    def update_camera_error(self, text: str):
        self._status_label.setText(f"Error: {text}")
        self._status_label.setStyleSheet("color: red;")

    def update_camera_fps(self, fps: float):
        self._fps_label.setText(f"FPS: {fps:.1f}")

    def update_camera_parameters(self, params: dict):
        pass  # TODO: update Hikvision parameter display

    def update_camera_devices(self, devices: list):
        pass  # TODO: update device list

    def sync_camera_type(self, camera_type: str):
        self._camera_type = camera_type
        self._status_label.setText(f"Camera: {camera_type}")
