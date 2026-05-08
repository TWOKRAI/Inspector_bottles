# -*- coding: utf-8 -*-
"""
Тестовое GUI-приложение для отладки камеры Hikvision.

Работает напрямую через HikvisionCamera (single-process),
без ProcessManager или multiprocess_framework.
"""
from __future__ import annotations

import sys
import time
import traceback
from typing import Optional

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hikvision_camera_module_2.core.camera import HikvisionCamera, CameraState
from hikvision_camera_module_2.core.discovery import DeviceInfo, enum_devices
from hikvision_camera_module_2.core.converter import FrameConverter
from hikvision_camera_module_2.core.parameters import CameraParameters, get_parameters, set_parameters


class CameraTestWindow(QMainWindow):
    """Главное окно тестового приложения камеры Hikvision.

    Предоставляет полный цикл управления камерой:
    выбор устройства → открытие → захват кадров → настройка параметров.
    """

    def __init__(self) -> None:
        super().__init__()

        # Экземпляр камеры (создаётся при открытии)
        self._camera: HikvisionCamera | None = None

        # Список обнаруженных устройств
        self._devices: list[DeviceInfo] = []

        # Счётчик FPS
        self._fps_counter: int = 0
        self._fps_start: float = time.time()
        self._fps_value: float = 0.0

        # Таймер для обновления live view (~30 FPS для UI)
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)
        self._frame_timer.timeout.connect(self._update_frame)

        self._init_ui()
        self._update_controls()

    # ── Инициализация UI ─────────────────────────────────────────────────

    def _init_ui(self) -> None:
        """Инициализировать интерфейс главного окна."""
        self.setWindowTitle("Тест камеры Hikvision — SDK App v2")
        self.setGeometry(100, 100, 1050, 720)

        # Центральный виджет
        central = QWidget()
        self.setCentralWidget(central)

        # Основной горизонтальный layout
        main_layout = QHBoxLayout(central)

        # Левая панель управления (фиксированная ширина)
        control_panel = self._create_control_panel()
        main_layout.addWidget(control_panel)

        # Правая панель: отображение кадра
        self._image_label = QLabel("Нет изображения")
        self._image_label.setMinimumSize(640, 480)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet(
            "background-color: black; color: white; border: 2px solid #444;"
        )
        main_layout.addWidget(self._image_label, stretch=1)

    def _create_control_panel(self) -> QWidget:
        """Создать левую панель управления.

        Возвращает виджет с тремя группами:
        выбор устройства, захват, параметры камеры.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        panel.setMaximumWidth(310)

        # ── Группа: Выбор устройства ──────────────────────────────────
        device_group = QGroupBox("Выбор устройства")
        device_layout = QVBoxLayout(device_group)

        # Кнопка поиска устройств
        self._btn_enum = QPushButton("Найти устройства")
        self._btn_enum.clicked.connect(self._enum_devices)
        device_layout.addWidget(self._btn_enum)

        # Выпадающий список найденных устройств
        self._combo_devices = QComboBox()
        device_layout.addWidget(self._combo_devices)

        # Кнопки Открыть / Закрыть
        open_close_layout = QHBoxLayout()

        self._btn_open = QPushButton("Открыть")
        self._btn_open.clicked.connect(self._open_device)
        open_close_layout.addWidget(self._btn_open)

        self._btn_close = QPushButton("Закрыть")
        self._btn_close.clicked.connect(self._close_device)
        open_close_layout.addWidget(self._btn_close)

        device_layout.addLayout(open_close_layout)
        layout.addWidget(device_group)

        # ── Группа: Захват изображения ────────────────────────────────
        self._group_grab = QGroupBox("Захват изображения")
        grab_layout = QVBoxLayout(self._group_grab)

        start_stop_layout = QHBoxLayout()

        self._btn_start = QPushButton("Начать захват")
        self._btn_start.clicked.connect(self._start_grabbing)
        start_stop_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("Остановить")
        self._btn_stop.clicked.connect(self._stop_grabbing)
        start_stop_layout.addWidget(self._btn_stop)

        grab_layout.addLayout(start_stop_layout)
        layout.addWidget(self._group_grab)

        # ── Группа: Параметры камеры ──────────────────────────────────
        self._group_params = QGroupBox("Параметры камеры")
        params_layout = QGridLayout(self._group_params)

        # Частота кадров
        params_layout.addWidget(QLabel("Частота кадров:"), 0, 0)
        self._edit_frame_rate = QLineEdit("0.00")
        self._edit_frame_rate.setPlaceholderText("FPS")
        params_layout.addWidget(self._edit_frame_rate, 0, 1)

        # Время экспозиции
        params_layout.addWidget(QLabel("Экспозиция:"), 1, 0)
        self._edit_exposure = QLineEdit("0.00")
        self._edit_exposure.setPlaceholderText("мкс")
        params_layout.addWidget(self._edit_exposure, 1, 1)

        # Усиление (gain)
        params_layout.addWidget(QLabel("Усиление:"), 2, 0)
        self._edit_gain = QLineEdit("0.00")
        self._edit_gain.setPlaceholderText("дБ")
        params_layout.addWidget(self._edit_gain, 2, 1)

        # Кнопки управления параметрами
        params_btn_layout = QHBoxLayout()

        self._btn_get_params = QPushButton("Получить")
        self._btn_get_params.clicked.connect(self._get_parameters)
        params_btn_layout.addWidget(self._btn_get_params)

        self._btn_set_params = QPushButton("Применить")
        self._btn_set_params.clicked.connect(self._set_parameters)
        params_btn_layout.addWidget(self._btn_set_params)

        params_layout.addLayout(params_btn_layout, 3, 0, 1, 2)
        layout.addWidget(self._group_params)

        # ── Статус и FPS ──────────────────────────────────────────────
        self._status_label = QLabel(
            "Статус: Готов\nНажмите «Найти устройства» для поиска камер"
        )
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "padding: 10px; background-color: #f0f0f0; border: 1px solid #ccc;"
        )
        layout.addWidget(self._status_label)

        # Счётчик FPS
        self._fps_label = QLabel("FPS: 0.0")
        self._fps_label.setStyleSheet(
            "padding: 5px; background-color: #e0e0e0; "
            "border: 1px solid #ccc; font-weight: bold;"
        )
        layout.addWidget(self._fps_label)

        layout.addStretch()

        return panel

    # ── Callbacks камеры ─────────────────────────────────────────────────

    def _on_camera_status(self, message: str) -> None:
        """Callback: статусное сообщение от камеры."""
        self._set_status(message)

    def _on_camera_error(self, message: str) -> None:
        """Callback: ошибка от камеры."""
        self._set_status(f"Ошибка: {message}")
        print(f"[CameraError] {message}")

    # ── Вспомогательные методы ───────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        """Обновить статусную строку."""
        self._status_label.setText(f"Статус: {text}")

    def _camera_state(self) -> CameraState:
        """Получить текущее состояние камеры (CLOSED если нет экземпляра)."""
        if self._camera is None:
            return CameraState.CLOSED
        return self._camera.state

    # ── Управление устройством ───────────────────────────────────────────

    def _enum_devices(self) -> None:
        """Перечислить доступные камеры GigE/USB."""
        try:
            self._set_status("Поиск устройств...")
            QApplication.processEvents()

            devices = enum_devices()

            if not devices:
                QMessageBox.information(
                    self,
                    "Информация",
                    "Камеры не найдены. Проверьте подключение и наличие SDK.",
                )
                self._set_status("Камеры не найдены")
                self._devices = []
                self._combo_devices.clear()
                self._update_controls()
                return

            # Сохраняем список и заполняем комбобокс
            self._devices = devices
            self._combo_devices.clear()
            for device in devices:
                self._combo_devices.addItem(device.display_name)

            self._set_status(
                f"Найдено: {len(devices)} устройств(о). "
                "Выберите и нажмите «Открыть»"
            )

            print(f"[Enum] Найдено {len(devices)} устройств:")
            for dev in devices:
                print(f"  - {dev.display_name}")

            self._update_controls()

        except Exception as exc:
            self._set_status(f"Ошибка поиска: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при поиске устройств:\n{exc}")
            traceback.print_exc()

    def _open_device(self) -> None:
        """Открыть выбранную камеру."""
        try:
            if self._camera_state() != CameraState.CLOSED:
                QMessageBox.warning(self, "Предупреждение", "Камера уже открыта!")
                return

            if not self._devices:
                QMessageBox.warning(
                    self, "Предупреждение", "Сначала выполните поиск устройств!"
                )
                return

            camera_index = self._combo_devices.currentIndex()
            if camera_index < 0:
                QMessageBox.warning(self, "Предупреждение", "Выберите камеру из списка!")
                return

            device_name = self._devices[camera_index].display_name
            self._set_status(f"Открытие камеры [{camera_index}]...")
            QApplication.processEvents()

            # Создаём новый экземпляр камеры
            self._camera = HikvisionCamera(
                on_status=self._on_camera_status,
                on_error=self._on_camera_error,
            )

            success = self._camera.open(camera_index)

            if success:
                self._set_status(f"Камера открыта: {device_name}")
                print(f"[Open] Камера открыта: {device_name}")
                # Автоматически читаем параметры после открытия
                self._get_parameters()
            else:
                self._set_status("Не удалось открыть камеру")
                QMessageBox.critical(
                    self, "Ошибка", "Не удалось открыть камеру.\nПроверьте подключение."
                )
                self._camera = None

            self._update_controls()

        except Exception as exc:
            self._set_status(f"Ошибка: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при открытии:\n{exc}")
            self._camera = None
            self._update_controls()
            traceback.print_exc()

    def _close_device(self) -> None:
        """Закрыть камеру."""
        try:
            if self._camera_state() == CameraState.CLOSED:
                return

            # Останавливаем захват если активен
            if self._camera_state() == CameraState.GRABBING:
                self._stop_grabbing()

            self._set_status("Закрытие камеры...")
            QApplication.processEvents()

            if self._camera is not None:
                self._camera.close()
                self._camera = None

            # Очищаем отображение кадра
            self._image_label.clear()
            self._image_label.setText("Нет изображения")

            self._set_status("Камера закрыта")
            print("[Close] Камера закрыта")
            self._update_controls()

        except Exception as exc:
            self._set_status(f"Ошибка при закрытии: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при закрытии:\n{exc}")
            traceback.print_exc()

    # ── Управление захватом ──────────────────────────────────────────────

    def _start_grabbing(self) -> None:
        """Начать захват кадров."""
        try:
            if self._camera_state() == CameraState.CLOSED:
                QMessageBox.warning(self, "Предупреждение", "Сначала откройте камеру!")
                return

            if self._camera_state() == CameraState.GRABBING:
                QMessageBox.warning(self, "Предупреждение", "Захват уже запущен!")
                return

            self._set_status("Запуск захвата...")
            QApplication.processEvents()

            success = self._camera.start_grabbing()  # type: ignore[union-attr]

            if success:
                # Сбрасываем счётчик FPS
                self._fps_counter = 0
                self._fps_start = time.time()
                self._fps_value = 0.0

                # Запускаем таймер обновления кадра (~30 FPS для UI)
                self._frame_timer.start()
                self._set_status("Захват активен — получение кадров...")
                print("[Grab] Захват запущен")
            else:
                self._set_status("Не удалось запустить захват")
                QMessageBox.critical(
                    self, "Ошибка", "Не удалось запустить захват кадров."
                )

            self._update_controls()

        except Exception as exc:
            self._set_status(f"Ошибка: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка запуска захвата:\n{exc}")
            traceback.print_exc()

    def _stop_grabbing(self) -> None:
        """Остановить захват кадров."""
        try:
            if self._camera_state() != CameraState.GRABBING:
                return

            # Останавливаем UI-таймер первым
            self._frame_timer.stop()

            self._set_status("Остановка захвата...")
            QApplication.processEvents()

            if self._camera is not None:
                self._camera.stop_grabbing()

            self._set_status("Захват остановлен")
            print("[Grab] Захват остановлен")
            self._update_controls()

        except Exception as exc:
            self._set_status(f"Ошибка при остановке: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка остановки захвата:\n{exc}")
            traceback.print_exc()

    # ── Обновление кадра (вызывается таймером) ───────────────────────────

    def _update_frame(self) -> None:
        """Получить и отобразить один кадр из камеры.

        Вызывается таймером каждые 33 мс (~30 FPS UI).
        """
        if self._camera is None or self._camera.state != CameraState.GRABBING:
            return

        try:
            raw_frame, pixel_type = self._camera.capture_frame(timeout_ms=100)
        except Exception as exc:
            print(f"[Frame] Ошибка при capture_frame: {exc}")
            return

        if raw_frame is None:
            # Таймаут или нет кадра — ничего страшного, пропускаем итерацию
            return

        # ── Обновление счётчика FPS ──────────────────────────────────
        self._fps_counter += 1
        elapsed = time.time() - self._fps_start

        if elapsed >= 1.0:
            self._fps_value = self._fps_counter / elapsed
            self._fps_label.setText(f"FPS: {self._fps_value:.1f}")
            self._fps_counter = 0
            self._fps_start = time.time()

        # ── Конвертация через FrameConverter ─────────────────────────
        bgr_frame = FrameConverter.to_bgr(raw_frame, pixel_type)

        if bgr_frame is None:
            # Формат не поддерживается — пробуем отобразить как есть
            bgr_frame = self._fallback_display(raw_frame)
            if bgr_frame is None:
                return

        # ── Конвертация BGR → QImage ──────────────────────────────────
        q_image = self._ndarray_to_qimage(bgr_frame)
        if q_image is None:
            return

        # ── Масштабирование под размер label ─────────────────────────
        pixmap = QPixmap.fromImage(q_image)
        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    @staticmethod
    def _fallback_display(frame: np.ndarray) -> np.ndarray | None:
        """Попытка отобразить кадр неизвестного формата.

        Если 2D — трактуем как Grayscale и расширяем до 3 каналов.
        Если 3D с 3 каналами — возвращаем как есть.
        """
        import cv2

        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if frame.ndim == 3 and frame.shape[2] == 3:
            return frame
        return None

    @staticmethod
    def _ndarray_to_qimage(bgr: np.ndarray) -> Optional["QImage"]:
        """Конвертировать BGR ndarray в QImage.

        Параметры
        ---------
        bgr : np.ndarray
            Кадр в формате BGR (3 канала, uint8).

        Возвращает
        ----------
        QImage | None
        """
        if bgr is None or bgr.size == 0:
            return None

        # Убеждаемся что массив C-contiguous
        if not bgr.flags["C_CONTIGUOUS"]:
            bgr = np.ascontiguousarray(bgr)

        height, width = bgr.shape[:2]

        if bgr.ndim == 3 and bgr.shape[2] == 3:
            # BGR → RGB для QImage
            rgb = bgr[:, :, ::-1].copy()
            bytes_per_line = width * 3
            return QImage(rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)

        if bgr.ndim == 2:
            # Grayscale
            bytes_per_line = width
            return QImage(bgr.data, width, height, bytes_per_line, QImage.Format_Grayscale8)

        return None

    # ── Параметры камеры ─────────────────────────────────────────────────

    def _get_parameters(self) -> None:
        """Прочитать текущие параметры камеры и отобразить в полях ввода."""
        if self._camera_state() == CameraState.CLOSED or self._camera is None:
            QMessageBox.warning(self, "Предупреждение", "Сначала откройте камеру!")
            return

        self._set_status("Чтение параметров камеры...")
        QApplication.processEvents()

        try:
            params = get_parameters(self._camera._camera)

            if params is None:
                self._set_status("Не удалось получить параметры")
                QMessageBox.critical(
                    self, "Ошибка", "Не удалось получить параметры камеры."
                )
                return

            # Заполняем поля ввода
            self._edit_frame_rate.setText(f"{params.frame_rate:.2f}")
            self._edit_exposure.setText(f"{params.exposure_time:.2f}")
            self._edit_gain.setText(f"{params.gain:.2f}")

            self._set_status(
                f"Параметры получены: "
                f"FPS={params.frame_rate:.1f}, "
                f"Exp={params.exposure_time:.1f}мкс, "
                f"Gain={params.gain:.2f}дБ"
            )
            print(f"[Params] frame_rate={params.frame_rate:.2f}, "
                  f"exposure={params.exposure_time:.2f}, gain={params.gain:.2f}")

        except Exception as exc:
            self._set_status(f"Ошибка чтения параметров: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при чтении параметров:\n{exc}")
            traceback.print_exc()

    def _set_parameters(self) -> None:
        """Применить параметры из полей ввода к камере."""
        if self._camera_state() == CameraState.CLOSED or self._camera is None:
            QMessageBox.warning(self, "Предупреждение", "Сначала откройте камеру!")
            return

        # Считываем значения из полей ввода
        try:
            frame_rate = float(self._edit_frame_rate.text())
            exposure_time = float(self._edit_exposure.text())
            gain = float(self._edit_gain.text())
        except ValueError:
            QMessageBox.warning(
                self, "Предупреждение", "Введите корректные числовые значения!"
            )
            return

        self._set_status("Применение параметров камеры...")
        QApplication.processEvents()

        try:
            params = CameraParameters(
                frame_rate=frame_rate,
                exposure_time=exposure_time,
                gain=gain,
            )

            success = set_parameters(self._camera._camera, params)

            if success:
                self._set_status(
                    f"Параметры применены: "
                    f"FPS={frame_rate:.1f}, "
                    f"Exp={exposure_time:.1f}мкс, "
                    f"Gain={gain:.2f}дБ"
                )
                print(f"[Params] Параметры применены: frame_rate={frame_rate:.2f}, "
                      f"exposure={exposure_time:.2f}, gain={gain:.2f}")
            else:
                self._set_status("Не удалось применить параметры")
                QMessageBox.critical(
                    self, "Ошибка", "Не удалось применить параметры камеры."
                )

        except Exception as exc:
            self._set_status(f"Ошибка применения параметров: {exc}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при установке параметров:\n{exc}")
            traceback.print_exc()

    # ── Управление доступностью элементов (state machine) ────────────────

    def _update_controls(self) -> None:
        """Включить/выключить элементы управления согласно текущему состоянию.

        Логика state machine:
        - CLOSED: можно искать устройства и открывать
        - OPEN: можно закрыть и начать захват
        - GRABBING: можно только остановить захват
        """
        state = self._camera_state()
        has_devices = len(self._devices) > 0

        is_closed = state == CameraState.CLOSED
        is_open = state == CameraState.OPEN
        is_grabbing = state == CameraState.GRABBING

        # Группа выбора устройства
        self._btn_enum.setEnabled(is_closed)
        self._combo_devices.setEnabled(is_closed and has_devices)
        self._btn_open.setEnabled(is_closed and has_devices)
        self._btn_close.setEnabled(not is_closed)

        # Группа захвата
        self._group_grab.setEnabled(not is_closed)
        self._btn_start.setEnabled(is_open)
        self._btn_stop.setEnabled(is_grabbing)

        # Группа параметров
        self._group_params.setEnabled(not is_closed)
        self._btn_get_params.setEnabled(not is_closed)
        # Параметры можно менять только когда захват НЕ идёт (безопасность)
        self._btn_set_params.setEnabled(is_open)

    # ── Закрытие окна ────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Обработать закрытие окна — корректно завершить работу с камерой."""
        print("[App] Закрытие приложения...")

        # Останавливаем таймер UI
        self._frame_timer.stop()

        # Останавливаем захват и закрываем камеру
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception as exc:
                print(f"[App] Ошибка при закрытии камеры: {exc}")
            self._camera = None

        event.accept()
        print("[App] Приложение закрыто")


def main() -> None:
    """Точка входа GUI-приложения."""
    app = QApplication(sys.argv)

    print("=" * 60)
    print("Тест камеры Hikvision — SDK App v2 (PySide6)")
    print("=" * 60)
    print("Прямая работа с HikvisionCamera (без ProcessManager)")
    print("Возможности: поиск устройств, захват, FPS, параметры")
    print("=" * 60)

    window = CameraTestWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
