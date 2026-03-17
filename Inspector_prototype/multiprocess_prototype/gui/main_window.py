# multiprocess_prototype\gui\main_window.py
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
    QComboBox,
    QLineEdit,
    QStackedWidget,
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

    def __init__(
        self,
        title: str,
        width: int,
        height: int,
        process,
        camera_type: str = "simulator",
    ):
        super().__init__()
        self.process = process
        self._camera_type = camera_type
        self._hikvision_devices: list = []
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
        self._video_label_original.setMinimumSize(280, 180)
        self._video_label_original.setStyleSheet("background-color: #1e1e1e; color: white;")
        video_layout.addWidget(self._video_label_original, 1)

        self._video_label_mask = QLabel("Mask (waiting...)")
        self._video_label_mask.setAlignment(Qt.AlignCenter)
        self._video_label_mask.setMinimumSize(280, 180)
        self._video_label_mask.setStyleSheet("background-color: #1e1e1e; color: white;")
        video_layout.addWidget(self._video_label_mask, 1)

        main_layout.addWidget(video_container, 3)

        # Правая панель — управление
        control_panel = QVBoxLayout()
        main_layout.addLayout(control_panel, 1)

        # Выпадающий список: тип камеры (переключение без перезапуска)
        camera_type_group = QGroupBox("Тип камеры")
        camera_type_layout = QVBoxLayout()
        camera_type_group.setLayout(camera_type_layout)

        self._combo_camera_type = QComboBox()
        self._combo_camera_type.addItems(["Simulator", "Webcam", "Hikvision"])
        self._combo_camera_type.setMinimumWidth(180)
        self._camera_type_map = {"simulator": 0, "webcam": 1, "hikvision": 2}
        self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(self._camera_type_map.get(self._camera_type, 2))
        self._combo_camera_type.blockSignals(False)
        self._combo_camera_type.currentIndexChanged.connect(self._on_camera_type_changed)
        camera_type_layout.addWidget(self._combo_camera_type)

        control_panel.addWidget(camera_type_group)

        # QStackedWidget: страница 0 = simulator/webcam, страница 1 = Hikvision
        self._camera_stack = QStackedWidget()

        # Страница 0: Simulator / Webcam
        page_sim = QWidget()
        layout_sim = QVBoxLayout()
        page_sim.setLayout(layout_sim)
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
        layout_sim.addWidget(btn_group)
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
        layout_sim.addWidget(fps_group)
        layout_sim.addStretch()
        self._camera_stack.addWidget(page_sim)

        # Страница 1: Hikvision
        page_hik = QWidget()
        layout_hik = QVBoxLayout()
        page_hik.setLayout(layout_hik)
        self._build_hikvision_panel(layout_hik)
        layout_hik.addStretch()
        self._camera_stack.addWidget(page_hik)

        control_panel.addWidget(self._camera_stack)

        # Переключить на нужную страницу
        self._camera_stack.setCurrentIndex(1 if self._camera_type == "hikvision" else 0)

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

        self._camera_fps_label = QLabel("Camera FPS: —")
        self._camera_fps_label.setStyleSheet("color: #2ecc71; font-weight: bold;")
        control_panel.addWidget(self._camera_fps_label)

        control_panel.addStretch()

        self._frame_count = 0

    def _build_hikvision_panel(self, control_panel: QVBoxLayout) -> None:
        """Панель управления Hikvision SDK (как в ui_camera_test_2)."""
        # Устройство
        dev_group = QGroupBox("Устройство")
        dev_layout = QVBoxLayout()
        dev_group.setLayout(dev_layout)

        self._combo_devices = QComboBox()
        self._combo_devices.setMinimumWidth(200)
        self._combo_devices.addItem("— выберите устройство —")
        dev_layout.addWidget(self._combo_devices)

        btn_enum = QPushButton("Enum Devices")
        btn_enum.clicked.connect(self.process.gui_enum_devices)
        dev_layout.addWidget(btn_enum)

        row_open = QHBoxLayout()
        self._btn_open = QPushButton("Open")
        self._btn_open.clicked.connect(self._on_hikvision_open)
        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.process.gui_close_camera)
        row_open.addWidget(self._btn_open)
        row_open.addWidget(self._btn_close)
        dev_layout.addLayout(row_open)

        control_panel.addWidget(dev_group)

        # Grabbing
        grab_group = QGroupBox("Grabbing")
        grab_layout = QVBoxLayout()
        grab_group.setLayout(grab_layout)

        self._btn_start_grabbing = QPushButton("▶ Start Grabbing")
        self._btn_start_grabbing.clicked.connect(self._on_hikvision_start_grabbing)
        self._btn_stop_grabbing = QPushButton("■ Stop Grabbing")
        self._btn_stop_grabbing.clicked.connect(self.process.gui_stop_grabbing)
        grab_layout.addWidget(self._btn_start_grabbing)
        grab_layout.addWidget(self._btn_stop_grabbing)

        control_panel.addWidget(grab_group)

        # Параметры (Frame Rate, Exposure, Gain)
        params_group = QGroupBox("Параметры камеры")
        params_layout = QVBoxLayout()
        params_group.setLayout(params_layout)

        row_fr = QHBoxLayout()
        row_fr.addWidget(QLabel("Frame Rate:"))
        self._edit_frame_rate = QLineEdit()
        self._edit_frame_rate.setPlaceholderText("FPS")
        self._edit_frame_rate.setMaximumWidth(80)
        row_fr.addWidget(self._edit_frame_rate)
        params_layout.addLayout(row_fr)

        row_exp = QHBoxLayout()
        row_exp.addWidget(QLabel("Exposure:"))
        self._edit_exposure = QLineEdit()
        self._edit_exposure.setPlaceholderText("μs")
        self._edit_exposure.setMaximumWidth(80)
        row_exp.addWidget(self._edit_exposure)
        params_layout.addLayout(row_exp)

        row_gain = QHBoxLayout()
        row_gain.addWidget(QLabel("Gain:"))
        self._edit_gain = QLineEdit()
        self._edit_gain.setPlaceholderText("dB")
        self._edit_gain.setMaximumWidth(80)
        row_gain.addWidget(self._edit_gain)
        params_layout.addLayout(row_gain)

        row_btns = QHBoxLayout()
        self._btn_get_params = QPushButton("Get Parameters")
        self._btn_get_params.clicked.connect(self.process.gui_get_parameters)
        self._btn_set_params = QPushButton("Set Parameters")
        self._btn_set_params.clicked.connect(self._on_hikvision_set_params)
        row_btns.addWidget(self._btn_get_params)
        row_btns.addWidget(self._btn_set_params)
        params_layout.addLayout(row_btns)

        control_panel.addWidget(params_group)

    def _get_selected_camera_index(self) -> int:
        """Индекс выбранного устройства в ComboBox (0 если ничего не выбрано)."""
        combo_idx = self._combo_devices.currentIndex()
        if combo_idx <= 0 or combo_idx > len(self._hikvision_devices):
            return 0
        dev = self._hikvision_devices[combo_idx - 1]
        return dev.get("index", 0)

    def _on_hikvision_open(self) -> None:
        self.process.gui_open_camera(camera_index=self._get_selected_camera_index())

    def _on_hikvision_start_grabbing(self) -> None:
        """Open (если нужно) + Start Grabbing — камера обработает команды по порядку."""
        self.process.gui_open_camera(camera_index=self._get_selected_camera_index())
        self.process.gui_start_grabbing()

    def _on_hikvision_set_params(self) -> None:
        try:
            fr = float(self._edit_frame_rate.text() or 25)
            exp = float(self._edit_exposure.text() or 10000)
            gain = float(self._edit_gain.text() or 0)
        except ValueError:
            return
        self.process.gui_set_parameters(fr, exp, gain)

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

    def update_camera_status(self, text: str):
        """Обновить статус от камеры (Hikvision)."""
        self._status_label.setText(f"Status: {text}")
        self._status_label.setStyleSheet("color: gray; padding: 5px;")

    def update_camera_error(self, text: str):
        """Показать ошибку камеры (Hikvision)."""
        self._status_label.setText(f"Error: {text}")
        self._status_label.setStyleSheet("color: #e74c3c; padding: 5px;")

    def update_camera_fps(self, fps: float):
        """Обновить отображение реального FPS с камеры."""
        if fps <= 0:
            self._camera_fps_label.setText("Camera FPS: —")
        else:
            self._camera_fps_label.setText(f"Camera FPS: {fps:.1f}")

    def update_camera_parameters(self, params: dict):
        """Обновить отображение параметров камеры (Hikvision)."""
        if not params:
            return
        if hasattr(self, "_fps_label") and "frame_rate" in params:
            self._fps_label.setText(f"{params['frame_rate']:.1f} FPS")
        if hasattr(self, "_edit_frame_rate"):
            self._edit_frame_rate.setText(f"{params.get('frame_rate', 0):.1f}")
        if hasattr(self, "_edit_exposure"):
            self._edit_exposure.setText(f"{params.get('exposure_time', 0):.0f}")
        if hasattr(self, "_edit_gain"):
            self._edit_gain.setText(f"{params.get('gain', 0):.1f}")

    def update_camera_devices(self, devices: list):
        """Список устройств (Hikvision) — заполнить ComboBox."""
        self._hikvision_devices = devices or []
        combo = getattr(self, "_combo_devices", None)
        if not combo:
            return
        combo.clear()
        combo.addItem("— выберите устройство —")
        for dev in self._hikvision_devices:
            display = dev.get("display_name", f"[{dev.get('index', '?')}]")
            combo.addItem(display)

    def _on_camera_type_changed(self, index: int):
        """Переключение типа камеры без перезапуска."""
        rev_map = {0: "simulator", 1: "webcam", 2: "hikvision"}
        new_type = rev_map.get(index, "hikvision")
        self._camera_type = new_type
        self.process.gui_camera_type_changed(new_type)
        self._camera_stack.setCurrentIndex(1 if new_type == "hikvision" else 0)

    def sync_camera_type(self, camera_type: str):
        """Синхронизация UI при получении camera_type_changed от камеры."""
        self._camera_type = camera_type
        idx = self._camera_type_map.get(camera_type, 0)
        self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(idx)
        self._combo_camera_type.blockSignals(False)
        self._camera_stack.setCurrentIndex(1 if camera_type == "hikvision" else 0)

    def _on_fps_changed(self, value: int):
        self._fps_label.setText(f"{value} FPS")
        if hasattr(self.process, "gui_set_fps"):
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
