# -*- coding: utf-8 -*-
"""
Чистое тестовое приложение без обработки изображения
Использует оригинальную логику из BasicDemo.py
"""

import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QPushButton, QLabel, QComboBox, 
                              QMessageBox, QGroupBox, QLineEdit, QGridLayout)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
import numpy as np
import time

import os

from hikvision_camera_module.sdk.clean_camera_process import CleanCameraProcessManager


class CleanCameraTest(QMainWindow):
    """
    Чистое тестовое приложение БЕЗ обработки изображения
    """
    
    def __init__(self):
        super().__init__()
        
        # Менеджер камеры
        self.camera_manager = None
        
        # Список устройств
        self.device_list = []
        
        # Состояние
        self.is_open = False
        self.is_grabbing = False
        
        # Таймер для обновления кадров (только для FPS счетчика)
        self.frame_timer = QTimer()
        self.frame_timer.timeout.connect(self.update_frame)
        
        # FPS счетчик
        self.fps_counter = 0
        self.fps_start_time = time.time()
        self.current_fps = 0.0
        
        # Параметры камеры
        self.camera_params = {
            'frame_rate': 0.0,
            'exposure_time': 0.0,
            'gain': 0.0
        }
        
        # Инициализация UI
        self.init_ui()
        self.enable_controls()
        
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle("Clean Camera Test - With Parameters & FPS")
        self.setGeometry(100, 100, 1000, 700)
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Левая панель - управление
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
        
        # Правая панель - отображение изображения
        self.image_label = QLabel("No image")
        self.image_label.setMinimumSize(640, 480)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: black; color: white; border: 2px solid #444;")
        main_layout.addWidget(self.image_label, stretch=1)
        
    def create_control_panel(self):
        """Создать панель управления"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        panel.setMaximumWidth(300)
        
        # ===== Группа: Выбор устройства =====
        device_group = QGroupBox("Device Selection")
        device_layout = QVBoxLayout()
        device_group.setLayout(device_layout)
        
        # Кнопка Enum
        self.btn_enum = QPushButton("Enum Devices")
        self.btn_enum.clicked.connect(self.enum_devices)
        device_layout.addWidget(self.btn_enum)
        
        # Комбобокс
        self.combo_devices = QComboBox()
        device_layout.addWidget(self.combo_devices)
        
        # Кнопки Open/Close
        btn_layout = QHBoxLayout()
        
        self.btn_open = QPushButton("Open")
        self.btn_open.clicked.connect(self.open_device)
        btn_layout.addWidget(self.btn_open)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close_device)
        btn_layout.addWidget(self.btn_close)
        
        device_layout.addLayout(btn_layout)
        
        layout.addWidget(device_group)
        
        # ===== Группа: Захват =====
        self.group_grab = QGroupBox("Image Acquisition")
        grab_layout = QVBoxLayout()
        self.group_grab.setLayout(grab_layout)
        
        # Кнопки Start/Stop
        startstop_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("Start Grabbing")
        self.btn_start.clicked.connect(self.start_grabbing)
        startstop_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("Stop Grabbing")
        self.btn_stop.clicked.connect(self.stop_grabbing)
        startstop_layout.addWidget(self.btn_stop)
        
        grab_layout.addLayout(startstop_layout)
        
        layout.addWidget(self.group_grab)
        
        # ===== Группа: Параметры камеры =====
        self.group_params = QGroupBox("Camera Parameters")
        params_layout = QGridLayout()
        self.group_params.setLayout(params_layout)
        
        # Frame Rate
        params_layout.addWidget(QLabel("Frame Rate:"), 0, 0)
        self.edit_frame_rate = QLineEdit("0")
        self.edit_frame_rate.setPlaceholderText("FPS")
        params_layout.addWidget(self.edit_frame_rate, 0, 1)
        
        # Exposure Time
        params_layout.addWidget(QLabel("Exposure:"), 1, 0)
        self.edit_exposure = QLineEdit("0")
        self.edit_exposure.setPlaceholderText("μs")
        params_layout.addWidget(self.edit_exposure, 1, 1)
        
        # Gain
        params_layout.addWidget(QLabel("Gain:"), 2, 0)
        self.edit_gain = QLineEdit("0")
        self.edit_gain.setPlaceholderText("dB")
        params_layout.addWidget(self.edit_gain, 2, 1)
        
        # Кнопки управления параметрами
        btn_params_layout = QHBoxLayout()
        
        self.btn_get_params = QPushButton("Get Parameters")
        self.btn_get_params.clicked.connect(self.get_camera_parameters)
        btn_params_layout.addWidget(self.btn_get_params)
        
        self.btn_set_params = QPushButton("Set Parameters")
        self.btn_set_params.clicked.connect(self.set_camera_parameters)
        btn_params_layout.addWidget(self.btn_set_params)
        
        params_layout.addLayout(btn_params_layout, 3, 0, 1, 2)
        
        layout.addWidget(self.group_params)
        
        # ===== Статус и FPS =====
        self.status_label = QLabel("Status: Ready\nPress 'Enum Devices' to find cameras")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.status_label)
        
        # FPS счетчик
        self.fps_label = QLabel("FPS: 0.0")
        self.fps_label.setStyleSheet("padding: 5px; background-color: #e0e0e0; border: 1px solid #ccc; font-weight: bold;")
        layout.addWidget(self.fps_label)
        
        layout.addStretch()
        
        return panel
    
    def enum_devices(self):
        """Перечислить доступные камеры"""
        try:
            self.status_label.setText("Status: Searching for devices...")
            QApplication.processEvents()
            
            result = CleanCameraProcessManager.enum_devices()
            
            if result.get('status') == 'error':
                error = result.get('error', 'Unknown error')
                QMessageBox.warning(self, "Error", f"Enum devices failed: {error}", QMessageBox.Ok)
                self.status_label.setText(f"Status: Error - {error}")
                return
            
            devices = result.get('devices', [])
            
            if len(devices) == 0:
                QMessageBox.information(self, "Info", "No devices found", QMessageBox.Ok)
                self.status_label.setText("Status: No devices found")
                return
            
            # Сохраняем список устройств
            self.device_list = devices
            
            # Заполняем комбобокс
            self.combo_devices.clear()
            for device in devices:
                self.combo_devices.addItem(device['display_name'])
            
            self.status_label.setText(f"Status: Found {len(devices)} device(s)\nSelect device and press 'Open'")
            
            # Включаем кнопку Open
            self.enable_controls()
            
            print(f"OK: Found {len(devices)} device(s)")
            for device in devices:
                print(f"  - {device['display_name']}")
                
        except Exception as e:
            error_msg = f"Exception in enum_devices: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            self.status_label.setText(f"Status: Error - {str(e)}")
            import traceback
            traceback.print_exc()
    
    def open_device(self):
        """Открыть выбранную камеру"""
        try:
            if self.is_open:
                QMessageBox.warning(self, "Warning", "Camera is already open!", QMessageBox.Ok)
                return
            
            if len(self.device_list) == 0:
                QMessageBox.warning(self, "Warning", "Please enumerate devices first!", QMessageBox.Ok)
                return
            
            # Получаем выбранный индекс
            camera_index = self.combo_devices.currentIndex()
            
            if camera_index < 0:
                QMessageBox.warning(self, "Warning", "Please select a camera!", QMessageBox.Ok)
                return
            
            self.status_label.setText(f"Status: Opening camera {camera_index}...")
            QApplication.processEvents()
            
            # Создаем менеджер камеры
            self.camera_manager = CleanCameraProcessManager()
            
            # Запускаем процесс камеры
            if not self.camera_manager.start_process(camera_index):
                QMessageBox.critical(self, "Error", "Failed to start camera process", QMessageBox.Ok)
                self.status_label.setText("Status: Failed to start process")
                self.camera_manager = None
                return
            
            # Открываем камеру
            response = self.camera_manager.open_camera()
            
            if response.get('status') == 'success':
                self.is_open = True
                self.status_label.setText(f"Status: Camera opened successfully\nDevice: {self.device_list[camera_index]['display_name']}")
                print("OK: Camera opened successfully")
                
                # Автоматически получаем параметры камеры
                self.get_camera_parameters()
            else:
                error = response.get('error', 'Unknown error')
                QMessageBox.critical(self, "Error", f"Failed to open camera: {error}", QMessageBox.Ok)
                self.status_label.setText(f"Status: Failed to open - {error}")
                
                # Останавливаем процесс
                self.camera_manager.stop_process()
                self.camera_manager = None
            
            self.enable_controls()
                
        except Exception as e:
            error_msg = f"Exception in open_device: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            self.status_label.setText(f"Status: Error - {str(e)}")
            import traceback
            traceback.print_exc()
    
    def close_device(self):
        """Закрыть камеру"""
        try:
            if not self.is_open:
                return
            
            # Останавливаем захват если активен
            if self.is_grabbing:
                self.stop_grabbing()
            
            self.status_label.setText("Status: Closing camera...")
            QApplication.processEvents()
            
            # Закрываем камеру
            if self.camera_manager is not None:
                response = self.camera_manager.close_camera()
                
                # Останавливаем процесс
                self.camera_manager.stop_process()
                self.camera_manager = None
            
            self.is_open = False
            self.status_label.setText("Status: Camera closed")
            
            # Очищаем изображение
            self.image_label.setText("No image")
            
            self.enable_controls()
            
            print("OK: Camera closed")
            
        except Exception as e:
            error_msg = f"Exception in close_device: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            import traceback
            traceback.print_exc()
    
    def start_grabbing(self):
        """Начать захват кадров"""
        try:
            if not self.is_open:
                QMessageBox.warning(self, "Warning", "Please open camera first!", QMessageBox.Ok)
                return
            
            if self.is_grabbing:
                QMessageBox.warning(self, "Warning", "Already grabbing!", QMessageBox.Ok)
                return
            
            self.status_label.setText("Status: Starting grabbing...")
            QApplication.processEvents()
            
            # Начинаем захват
            response = self.camera_manager.start_grabbing()
            
            if response.get('status') == 'success':
                self.is_grabbing = True
                self.status_label.setText("Status: Grabbing - receiving frames...")
                
                # Запускаем таймер для обновления кадров
                self.frame_timer.start(16)  # ~60 FPS для UI (16ms)
                
                print("OK: Grabbing started")
            else:
                error = response.get('error', 'Unknown error')
                QMessageBox.critical(self, "Error", f"Failed to start grabbing: {error}", QMessageBox.Ok)
                self.status_label.setText(f"Status: Failed to start - {error}")
            
            self.enable_controls()
                
        except Exception as e:
            error_msg = f"Exception in start_grabbing: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            import traceback
            traceback.print_exc()
    
    def stop_grabbing(self):
        """Остановить захват кадров"""
        try:
            if not self.is_grabbing:
                return
            
            # Останавливаем таймер
            self.frame_timer.stop()
            
            self.status_label.setText("Status: Stopping grabbing...")
            QApplication.processEvents()
            
            # Останавливаем захват
            response = self.camera_manager.stop_grabbing()
            
            self.is_grabbing = False
            self.status_label.setText("Status: Grabbing stopped")
            
            self.enable_controls()
            
            print("OK: Grabbing stopped")
                
        except Exception as e:
            error_msg = f"Exception in stop_grabbing: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            import traceback
            traceback.print_exc()
    
    def update_frame(self):
        """Обновить отображаемый кадр (вызывается таймером) - БЕЗ ОБРАБОТКИ"""
        try:
            if not self.is_grabbing or self.camera_manager is None:
                return
            
            # Получаем кадр
            frame = self.camera_manager.get_frame(timeout=0.1)
            
            if frame is not None:
                # Обновляем FPS счетчик
                self.fps_counter += 1
                current_time = time.time()
                time_diff = current_time - self.fps_start_time
                
                if time_diff >= 1.0:  # Обновляем FPS каждую секунду
                    self.current_fps = self.fps_counter / time_diff
                    self.fps_label.setText(f"FPS: {self.current_fps:.1f}")
                    print(f"UI FPS: {self.current_fps:.1f} (кадров за {time_diff:.1f}s)")
                    self.fps_counter = 0
                    self.fps_start_time = current_time
                
                # Отладочная информация (только при первом кадре)
                if not hasattr(self, '_frame_debug_logged'):
                    print(f"Raw frame shape: {frame.shape}, dtype: {frame.dtype}")
                    self._frame_debug_logged = True
                
                # Конвертируем в QImage БЕЗ ОБРАБОТКИ
                height, width = frame.shape[:2]
                
                # Если изображение монохромное
                if len(frame.shape) == 2:
                    bytes_per_line = width
                    q_image = QImage(
                        frame.data,
                        width,
                        height,
                        bytes_per_line,
                        QImage.Format_Grayscale8
                    )
                # Если цветное (3 канала) - RGB
                elif len(frame.shape) == 3 and frame.shape[2] == 3:
                    frame_rgb = frame[:, :, ::-1].copy()
                    bytes_per_line = width * 3
                    q_image = QImage(
                        frame_rgb.data,
                        width,
                        height,
                        bytes_per_line,
                        QImage.Format_RGB888
                    )
                # Если цветное (4 канала - RGBA)
                elif len(frame.shape) == 3 and frame.shape[2] == 4:
                    bytes_per_line = width * 4
                    q_image = QImage(
                        frame.data,
                        width,
                        height,
                        bytes_per_line,
                        QImage.Format_RGBA8888
                    )
                else:
                    print(f"Unknown frame shape: {frame.shape}")
                    return
                
                # Масштабируем изображение под размер label
                pixmap = QPixmap.fromImage(q_image)
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                
                self.image_label.setPixmap(scaled_pixmap)
                
        except Exception as e:
            print(f"Error updating frame: {e}")
    
    def get_camera_parameters(self):
        """Получить параметры камеры"""
        try:
            if not self.is_open:
                QMessageBox.warning(self, "Warning", "Please open camera first!", QMessageBox.Ok)
                return
            
            self.status_label.setText("Status: Getting camera parameters...")
            QApplication.processEvents()
            
            # Отправляем команду получения параметров
            response = self.camera_manager.get_camera_parameters()
            
            if response.get('status') == 'success':
                params = response.get('parameters', {})
                
                # Обновляем поля ввода
                self.edit_frame_rate.setText(f"{params.get('frame_rate', 0):.2f}")
                self.edit_exposure.setText(f"{params.get('exposure_time', 0):.2f}")
                self.edit_gain.setText(f"{params.get('gain', 0):.2f}")
                
                # Сохраняем параметры
                self.camera_params.update(params)
                
                self.status_label.setText("Status: Parameters retrieved successfully")
                print("OK: Camera parameters retrieved")
            else:
                error = response.get('error', 'Unknown error')
                QMessageBox.critical(self, "Error", f"Failed to get parameters: {error}", QMessageBox.Ok)
                self.status_label.setText(f"Status: Failed to get parameters - {error}")
                
        except Exception as e:
            error_msg = f"Exception in get_camera_parameters: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            self.status_label.setText(f"Status: Error - {str(e)}")
            import traceback
            traceback.print_exc()
    
    def set_camera_parameters(self):
        """Установить параметры камеры"""
        try:
            if not self.is_open:
                QMessageBox.warning(self, "Warning", "Please open camera first!", QMessageBox.Ok)
                return
            
            # Получаем значения из полей ввода
            try:
                frame_rate = float(self.edit_frame_rate.text())
                exposure_time = float(self.edit_exposure.text())
                gain = float(self.edit_gain.text())
            except ValueError:
                QMessageBox.warning(self, "Warning", "Please enter valid numeric values!", QMessageBox.Ok)
                return
            
            self.status_label.setText("Status: Setting camera parameters...")
            QApplication.processEvents()
            
            # Отправляем команду установки параметров
            response = self.camera_manager.set_camera_parameters(frame_rate, exposure_time, gain)
            
            if response.get('status') == 'success':
                self.status_label.setText("Status: Parameters set successfully")
                print("OK: Camera parameters set")
            else:
                error = response.get('error', 'Unknown error')
                QMessageBox.critical(self, "Error", f"Failed to set parameters: {error}", QMessageBox.Ok)
                self.status_label.setText(f"Status: Failed to set parameters - {error}")
                
        except Exception as e:
            error_msg = f"Exception in set_camera_parameters: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg, QMessageBox.Ok)
            self.status_label.setText(f"Status: Error - {str(e)}")
            import traceback
            traceback.print_exc()
    
    def enable_controls(self):
        """Включить/выключить элементы управления"""
        # Device selection
        self.btn_enum.setEnabled(not self.is_open)
        self.combo_devices.setEnabled(not self.is_open and len(self.device_list) > 0)
        self.btn_open.setEnabled(not self.is_open and len(self.device_list) > 0)
        self.btn_close.setEnabled(self.is_open)
        
        # Grabbing
        self.group_grab.setEnabled(self.is_open)
        self.btn_start.setEnabled(self.is_open and not self.is_grabbing)
        self.btn_stop.setEnabled(self.is_open and self.is_grabbing)
        
        # Camera Parameters
        self.group_params.setEnabled(self.is_open)
        self.btn_get_params.setEnabled(self.is_open)
        self.btn_set_params.setEnabled(self.is_open)
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        print("Closing application...")
        
        # Останавливаем захват и закрываем камеру
        if self.is_grabbing:
            self.stop_grabbing()
        
        if self.is_open:
            self.close_device()
        
        event.accept()
        print("Application closed")


def main():
    """Главная функция"""
    app = QApplication(sys.argv)
    
    print("="*60)
    print("Clean Camera Test - With Parameters & FPS Counter")
    print("="*60)
    print("This app shows RAW camera data with camera parameter control")
    print("Features: Frame Rate, Exposure, Gain settings + Real-time FPS")
    print("="*60)
    
    window = CleanCameraTest()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
