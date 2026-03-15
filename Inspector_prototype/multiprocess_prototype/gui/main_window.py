"""InspectorWindow — главное окно приложения."""

import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSlider,
    QGroupBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QCloseEvent


def _frame_to_pixmap(frame: np.ndarray, label_size) -> "QPixmap":
    """Конвертировать BGR numpy frame в QPixmap для label."""
    if frame is None or frame.size == 0:
        return QPixmap()
    h, w, ch = frame.shape
    bytes_per_line = ch * w
    rgb = np.ascontiguousarray(frame[:, :, ::-1])
    q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
    pixmap = QPixmap.fromImage(q_img)
    return pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class InspectorWindow(QMainWindow):
    """Главное окно Inspector Prototype."""

    def __init__(self, title: str, width: int, height: int, process):
        super().__init__()
        self.process = process
        self.setWindowTitle(title)
        self.resize(width, height)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # Левая панель — два видео (оригинал | маска)
        video_container = QWidget()
        video_layout = QHBoxLayout()
        video_container.setLayout(video_layout)

        self._video_label_original = QLabel("Original (waiting...)")
        self._video_label_original.setAlignment(Qt.AlignCenter)
        self._video_label_original.setMinimumSize(320, 240)
        self._video_label_original.setStyleSheet("background-color: #1e1e1e; color: white;")
        video_layout.addWidget(self._video_label_original, 1)

        self._video_label_mask = QLabel("Mask (waiting...)")
        self._video_label_mask.setAlignment(Qt.AlignCenter)
        self._video_label_mask.setMinimumSize(320, 240)
        self._video_label_mask.setStyleSheet("background-color: #1e1e1e; color: white;")
        video_layout.addWidget(self._video_label_mask, 1)

        main_layout.addWidget(video_container, 3)

        # Правая панель — управление
        control_panel = QVBoxLayout()
        main_layout.addLayout(control_panel, 1)

        # Кнопки Start/Stop
        btn_group = QGroupBox("Управление камерой")
        btn_layout = QVBoxLayout()
        btn_group.setLayout(btn_layout)

        self._btn_start = QPushButton("▶ Start")
        self._btn_start.clicked.connect(self.process.gui_start_capture)
        self._btn_start.setStyleSheet("padding: 10px; font-size: 14px;")
        btn_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("■ Stop")
        self._btn_stop.clicked.connect(self.process.gui_stop_capture)
        self._btn_stop.setStyleSheet("padding: 10px; font-size: 14px;")
        btn_layout.addWidget(self._btn_stop)

        control_panel.addWidget(btn_group)

        # Слайдер FPS
        fps_group = QGroupBox("FPS")
        fps_layout = QVBoxLayout()
        fps_group.setLayout(fps_layout)
        self._fps_label = QLabel("25 FPS")
        self._fps_slider = QSlider(Qt.Horizontal)
        self._fps_slider.setRange(1, 60)
        self._fps_slider.setValue(25)
        self._fps_slider.valueChanged.connect(self._on_fps_changed)
        fps_layout.addWidget(self._fps_label)
        fps_layout.addWidget(self._fps_slider)
        control_panel.addWidget(fps_group)

        # Слайдеры BGR для детекции цвета
        color_group = QGroupBox("Цветовая детекция (BGR)")
        color_layout = QVBoxLayout()
        color_group.setLayout(color_layout)

        def _add_slider_row(name: str, default_lower: int, default_upper: int):
            row = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setMinimumWidth(50)
            row.addWidget(lbl)
            sl_lo = QSlider(Qt.Horizontal)
            sl_lo.setRange(0, 255)
            sl_lo.setValue(default_lower)
            sl_hi = QSlider(Qt.Horizontal)
            sl_hi.setRange(0, 255)
            sl_hi.setValue(default_upper)
            row.addWidget(sl_lo, 1)
            row.addWidget(sl_hi, 1)
            return sl_lo, sl_hi, row

        # BGR Lower / Upper — default для красного: [0,0,150] — [100,100,255]
        self._sl_b_lo, self._sl_b_hi, r_b = _add_slider_row("B", 0, 100)
        self._sl_g_lo, self._sl_g_hi, r_g = _add_slider_row("G", 0, 100)
        self._sl_r_lo, self._sl_r_hi, r_r = _add_slider_row("R", 150, 255)

        color_layout.addLayout(r_b)
        color_layout.addLayout(r_g)
        color_layout.addLayout(r_r)

        self._color_label = QLabel("Lower | Upper")
        self._color_label.setStyleSheet("font-size: 10px; color: gray;")
        color_layout.addWidget(self._color_label)

        for sl in (self._sl_b_lo, self._sl_b_hi, self._sl_g_lo, self._sl_g_hi, self._sl_r_lo, self._sl_r_hi):
            sl.valueChanged.connect(self._on_color_range_changed)

        control_panel.addWidget(color_group)

        # Мин. площадь контура
        area_group = QGroupBox("Мин. площадь")
        area_layout = QVBoxLayout()
        area_group.setLayout(area_layout)
        self._area_label = QLabel("500 px")
        self._area_slider = QSlider(Qt.Horizontal)
        self._area_slider.setRange(10, 5000)
        self._area_slider.setValue(500)
        self._area_slider.valueChanged.connect(self._on_min_area_changed)
        area_layout.addWidget(self._area_label)
        area_layout.addWidget(self._area_slider)
        control_panel.addWidget(area_group)

        # Чекбоксы отображения (отправляют команды в renderer)
        display_group = QGroupBox("Отображение")
        display_layout = QVBoxLayout()
        display_group.setLayout(display_layout)

        self._cb_original = QCheckBox("Original")
        self._cb_original.setChecked(True)
        self._cb_original.stateChanged.connect(self._on_show_original_changed)
        display_layout.addWidget(self._cb_original)

        self._cb_mask = QCheckBox("Mask")
        self._cb_mask.setChecked(True)
        self._cb_mask.stateChanged.connect(self._on_show_mask_changed)
        display_layout.addWidget(self._cb_mask)

        self._cb_contours = QCheckBox("Contours")
        self._cb_contours.setChecked(True)
        self._cb_contours.stateChanged.connect(self._on_draw_contours_changed)
        display_layout.addWidget(self._cb_contours)

        control_panel.addWidget(display_group)

        # Статус
        self._status_label = QLabel("Status: waiting")
        self._status_label.setStyleSheet("color: gray; padding: 5px;")
        control_panel.addWidget(self._status_label)

        self._frame_counter_label = QLabel("Frames: 0")
        control_panel.addWidget(self._frame_counter_label)

        control_panel.addStretch()

        self._frame_count = 0

    def closeEvent(self, event: QCloseEvent):
        """При закрытии окна (крестик) — запрос на остановку всех процессов."""
        if hasattr(self.process, "gui_request_shutdown"):
            self.process.gui_request_shutdown()
        event.accept()

    def update_frame(
        self,
        original_frame: np.ndarray,
        mask_frame: np.ndarray,
        frame_id: int,
        show_original: bool = True,
        show_mask: bool = True,
    ):
        """Обновить отображение кадров. Вызывается из QTimer callback."""
        self._frame_count += 1

        if show_original and original_frame is not None and original_frame.size > 0:
            pix = _frame_to_pixmap(original_frame, self._video_label_original.size())
            self._video_label_original.setPixmap(pix)
            self._video_label_original.setText("")
        else:
            self._video_label_original.setPixmap(QPixmap())
            self._video_label_original.setText("Original (off)" if not show_original else "Original (waiting...)")

        if show_mask and mask_frame is not None and mask_frame.size > 0:
            pix = _frame_to_pixmap(mask_frame, self._video_label_mask.size())
            self._video_label_mask.setPixmap(pix)
            self._video_label_mask.setText("")
        else:
            self._video_label_mask.setPixmap(QPixmap())
            self._video_label_mask.setText("Mask (off)" if not show_mask else "Mask (waiting...)")

        self._frame_counter_label.setText(f"Frames: {self._frame_count}")
        self._status_label.setText(f"Status: active | Frame #{frame_id}")

    def _on_fps_changed(self, value: int):
        self._fps_label.setText(f"{value} FPS")
        self.process.gui_set_fps(value)

    def _on_color_range_changed(self, _value=None):
        self._color_label.setText(
            f"B[{self._sl_b_lo.value()}-{self._sl_b_hi.value()}] "
            f"G[{self._sl_g_lo.value()}-{self._sl_g_hi.value()}] "
            f"R[{self._sl_r_lo.value()}-{self._sl_r_hi.value()}]"
        )
        self.process.gui_set_color_range(
            self._sl_b_lo.value(),
            self._sl_g_lo.value(),
            self._sl_r_lo.value(),
            self._sl_b_hi.value(),
            self._sl_g_hi.value(),
            self._sl_r_hi.value(),
        )

    def _on_min_area_changed(self, value: int):
        self._area_label.setText(f"{value} px")
        self.process.gui_set_min_area(value)

    def _on_show_original_changed(self, state):
        checked = state == Qt.Checked
        self.process.gui_set_show_original(checked)

    def _on_show_mask_changed(self, state):
        checked = state == Qt.Checked
        self.process.gui_set_show_mask(checked)

    def _on_draw_contours_changed(self, state):
        checked = state == Qt.Checked
        self.process.gui_set_draw_contours(checked)
