# ui_process.py
import sys
import time
import threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QPushButton, QLabel, QComboBox, 
                              QMessageBox, QGroupBox, QLineEdit, QGridLayout)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
import numpy as np
import queue

# from queue_manager import QueueManager

class CameraMessageThread(QThread):
    """Поток для асинхронного опроса сообщений от камеры"""
    message_received = pyqtSignal(dict)  # Сигнал с полученным сообщением
    
    def __init__(self, queue_manager):
        super().__init__()
        self.queue_manager = queue_manager
        self.running = True
        
    def run(self):
        """Основной цикл потока"""
        while self.running:
            try:
                print(f'ЖДЕМ camera_to_ui.get')
                # Блокирующее ожидание сообщения с таймаутом
                message = self.queue_manager.camera_to_ui.get(timeout=1)
                print(f'UI получил message{message}')

                if message:
                    self.message_received.emit(message)
            except queue.Empty:
                # Таймаут - продолжаем цикл
                continue
            except Exception as e:
                print(f"Error in message thread: {e}")
                break
    
    def stop(self):
        """Остановить поток"""
        self.running = False
        self.wait(2000)  # Ждем до 2 секунд для завершения


class CameraUI(QMainWindow):
    """
    UI процесс, который общается с процессом камеры через queue_manager
    """
    
    def __init__(self, queue_manager):
        super().__init__()
        
        self.queue_manager = queue_manager
        
        # Состояние
        self.camera_process = None
        self.is_open = False
        self.is_grabbing = False
        
        # Таймеры
        self.frame_timer = QTimer()
        self.frame_timer.timeout.connect(self.update_frame)
        
        # Флаг для отслеживания, был ли запущен таймер до скрытия
        self.frame_timer_was_running = False
        
        # self.command_timer = QTimer()
        # self.command_timer.timeout.connect(self.check_camera_messages)

        # Поток для опроса сообщений
        self.message_thread = CameraMessageThread(self.queue_manager)
        self.message_thread.message_received.connect(self.handle_camera_message)
        
        
        # FPS счетчик
        self.fps_counter = 0
        self.fps_start_time = time.time()
        self.current_fps = 0.0
        
        # Список устройств
        self.device_list = []
        
        # Инициализация UI
        self.init_ui()
        self.enable_controls()
        
        # Запускаем поток опроса сообщений
        self.message_thread.start()
        
        # Запускаем поток для обработки команд управления видимостью
        self.control_ui_thread = threading.Thread(target=self._control_ui_loop)
        self.control_ui_thread.daemon = True
        self.control_ui_thread.start()
        
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle("Independent Camera Process - UI")
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
        
        # Группа: Выбор устройства
        device_group = QGroupBox("Device Selection")
        device_layout = QVBoxLayout()
        device_group.setLayout(device_layout)
        
        self.btn_enum = QPushButton("Enum Devices")
        self.btn_enum.clicked.connect(self.enum_devices)
        device_layout.addWidget(self.btn_enum)
        
        self.combo_devices = QComboBox()
        device_layout.addWidget(self.combo_devices)
        
        btn_layout = QHBoxLayout()
        self.btn_open = QPushButton("Open")
        self.btn_open.clicked.connect(self.open_camera)
        btn_layout.addWidget(self.btn_open)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close_camera)
        btn_layout.addWidget(self.btn_close)
        device_layout.addLayout(btn_layout)
        
        layout.addWidget(device_group)
        
        # Группа: Захват
        self.group_grab = QGroupBox("Image Acquisition")
        grab_layout = QVBoxLayout()
        self.group_grab.setLayout(grab_layout)
        
        startstop_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start Grabbing")
        self.btn_start.clicked.connect(self.start_grabbing)
        startstop_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("Stop Grabbing")
        self.btn_stop.clicked.connect(self.stop_grabbing)
        startstop_layout.addWidget(self.btn_stop)
        grab_layout.addLayout(startstop_layout)
        
        layout.addWidget(self.group_grab)
        
        # Группа: Параметры камеры
        self.group_params = QGroupBox("Camera Parameters")
        params_layout = QGridLayout()
        self.group_params.setLayout(params_layout)
        
        params_layout.addWidget(QLabel("Frame Rate:"), 0, 0)
        self.edit_frame_rate = QLineEdit("0")
        params_layout.addWidget(self.edit_frame_rate, 0, 1)
        
        params_layout.addWidget(QLabel("Exposure:"), 1, 0)
        self.edit_exposure = QLineEdit("0")
        params_layout.addWidget(self.edit_exposure, 1, 1)
        
        params_layout.addWidget(QLabel("Gain:"), 2, 0)
        self.edit_gain = QLineEdit("0")
        params_layout.addWidget(self.edit_gain, 2, 1)
        
        btn_params_layout = QHBoxLayout()
        self.btn_get_params = QPushButton("Get Parameters")
        self.btn_get_params.clicked.connect(self.get_parameters)
        btn_params_layout.addWidget(self.btn_get_params)
        
        self.btn_set_params = QPushButton("Set Parameters")
        self.btn_set_params.clicked.connect(self.set_parameters)
        btn_params_layout.addWidget(self.btn_set_params)
        params_layout.addLayout(btn_params_layout, 3, 0, 1, 2)
        
        layout.addWidget(self.group_params)
        
        # Статус и FPS
        self.status_label = QLabel("Status: Ready\nPress 'Enum Devices' to find cameras")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.status_label)
        
        self.fps_label = QLabel("FPS: 0.0")
        self.fps_label.setStyleSheet("padding: 5px; background-color: #e0e0e0; border: 1px solid #ccc; font-weight: bold;")
        layout.addWidget(self.fps_label)
        
        layout.addStretch()
        
        return panel
    
    def enum_devices(self):
        """Запросить список камер у процесса камеры"""
        self.status_label.setText("Status: Requesting device list...")
        
        # Отправляем команду перечисления устройств
        self.queue_manager.ui_to_camera.put({
            'type': 'enum_devices'
        })

        print('put enum_devices')
    
    def open_camera(self):
        """Открыть камеру"""
        if self.is_open:
            QMessageBox.warning(self, "Warning", "Camera is already open!", QMessageBox.Ok)
            return
        
        if len(self.device_list) == 0:
            QMessageBox.warning(self, "Warning", "Please enumerate devices first!", QMessageBox.Ok)
            return
        
        camera_index = self.combo_devices.currentIndex()
        if camera_index < 0:
            QMessageBox.warning(self, "Warning", "Please select a camera!", QMessageBox.Ok)
            return
        
        selected_device = self.device_list[camera_index]
        real_camera_index = selected_device['index']
        
        self.status_label.setText(f"Status: Opening camera {real_camera_index}...")
        
        # Отправляем команду открытия камеры
        self.queue_manager.ui_to_camera.put({
            'type': 'open',
            'camera_index': real_camera_index
        })
    
    def close_camera(self):
        """Закрыть камеру"""
        if not self.is_open:
            return
        
        if self.is_grabbing:
            self.stop_grabbing()
        
        self.status_label.setText("Status: Closing camera...")
        
        # Отправляем команду закрытия камеры
        self.queue_manager.ui_to_camera.put({
            'type': 'close'
        })
    
    def start_grabbing(self):
        """Начать захват кадров"""
        if not self.is_open:
            QMessageBox.warning(self, "Warning", "Please open camera first!", QMessageBox.Ok)
            return
        
        if self.is_grabbing:
            QMessageBox.warning(self, "Warning", "Already grabbing!", QMessageBox.Ok)
            return
        
        self.status_label.setText("Status: Starting grabbing...")
        
        # Отправляем команду начала захвата
        self.queue_manager.ui_to_camera.put({
            'type': 'start_grabbing'
        })
    
    def stop_grabbing(self):
        """Остановить захват кадров"""
        if not self.is_grabbing:
            return
        
        self.status_label.setText("Status: Stopping grabbing...")
        
        # Отправляем команду остановки захвата
        self.queue_manager.ui_to_camera.put({
            'type': 'stop_grabbing'
        })
    
    def get_parameters(self):
        """Получить параметры камеры"""
        if not self.is_open:
            QMessageBox.warning(self, "Warning", "Please open camera first!", QMessageBox.Ok)
            return
        
        self.status_label.setText("Status: Getting camera parameters...")
        
        # Отправляем команду получения параметров
        self.queue_manager.ui_to_camera.put({
            'type': 'get_parameters'
        })
    
    def set_parameters(self):
        """Установить параметры камеры"""
        if not self.is_open:
            QMessageBox.warning(self, "Warning", "Please open camera first!", QMessageBox.Ok)
            return
        
        try:
            frame_rate = float(self.edit_frame_rate.text())
            exposure_time = float(self.edit_exposure.text())
            gain = float(self.edit_gain.text())
        except ValueError:
            QMessageBox.warning(self, "Warning", "Please enter valid numeric values!", QMessageBox.Ok)
            return
        
        self.status_label.setText("Status: Setting camera parameters...")
        
        # Отправляем команду установки параметров
        self.queue_manager.ui_to_camera.put({
            'type': 'set_parameters',
            'frame_rate': frame_rate,
            'exposure_time': exposure_time,
            'gain': gain
        })
    

    def handle_camera_message(self, message):
        """Обработать сообщение от процесса камеры"""
        msg_type = message.get('type')
        
        if msg_type == 'status':
            status = message.get('status')
            self.status_label.setText(f"Status: {status}")
            
            if status == 'process_ready':
                print("Camera process is ready")
            elif status == 'Camera opened successfully':
                self.is_open = True
                self.enable_controls()
            elif status == 'Camera closed':
                self.is_open = False
                self.is_grabbing = False
                self.enable_controls()
            elif status == 'Grabbing started':
                self.is_grabbing = True
                # Запускаем таймер только если окно видимо
                if self.isVisible():
                    self.frame_timer.start(16)
                else:
                    self.frame_timer_was_running = True
                self.enable_controls()
            elif status == 'Grabbing stopped':
                self.is_grabbing = False
                self.frame_timer.stop()
                self.frame_timer_was_running = False
                self.enable_controls()
                
        elif msg_type == 'error':
            error = message.get('error')
            QMessageBox.critical(self, "Error", error, QMessageBox.Ok)
            self.status_label.setText(f"Status: Error - {error}")
            
        elif msg_type == 'enum_devices_response':
            devices = message.get('devices', [])
            self.device_list = devices
            
            if len(devices) == 0:
                QMessageBox.information(self, "Info", "No devices found", QMessageBox.Ok)
                self.status_label.setText("Status: No devices found")
                return
            
            # Заполняем комбобокс
            self.combo_devices.clear()
            for device in devices:
                self.combo_devices.addItem(device['display_name'])
            
            self.status_label.setText(f"Status: Found {len(devices)} device(s)")
            self.enable_controls()
            
        elif msg_type == 'parameters_response':
            params = message.get('parameters', {})
            
            # Обновляем поля ввода
            self.edit_frame_rate.setText(f"{params.get('frame_rate', 0):.2f}")
            self.edit_exposure.setText(f"{params.get('exposure_time', 0):.2f}")
            self.edit_gain.setText(f"{params.get('gain', 0):.2f}")
            
            self.status_label.setText("Status: Parameters retrieved")
    
    def update_frame(self):
        """Обновить отображаемый кадр"""
        try:
            if not self.is_grabbing:
                return
            
            # Получаем кадр из очереди
            frame = self.queue_manager.frame_queue.get_nowait()
            
            if frame is not None:
                # Обновляем FPS счетчик
                self.fps_counter += 1
                current_time = time.time()
                time_diff = current_time - self.fps_start_time
                
                if time_diff >= 1.0:
                    self.current_fps = self.fps_counter / time_diff
                    self.fps_label.setText(f"FPS: {self.current_fps:.1f}")
                    self.fps_counter = 0
                    self.fps_start_time = current_time
                
                # Конвертируем в QImage
                height, width = frame.shape[:2]
                
                if len(frame.shape) == 2:
                    bytes_per_line = width
                    q_image = QImage(
                        frame.data,
                        width,
                        height,
                        bytes_per_line,
                        QImage.Format_Grayscale8
                    )
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
                else:
                    return
                
                # Масштабируем и отображаем
                pixmap = QPixmap.fromImage(q_image)
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                
                self.image_label.setPixmap(scaled_pixmap)
                
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Error updating frame: {e}")
    
    def enable_controls(self):
        """Включить/выключить элементы управления"""
        self.btn_enum.setEnabled(not self.is_open)
        self.combo_devices.setEnabled(not self.is_open and len(self.device_list) > 0)
        self.btn_open.setEnabled(not self.is_open and len(self.device_list) > 0)
        self.btn_close.setEnabled(self.is_open)
        
        self.group_grab.setEnabled(self.is_open)
        self.btn_start.setEnabled(self.is_open and not self.is_grabbing)
        self.btn_stop.setEnabled(self.is_open and self.is_grabbing)
        
        self.group_params.setEnabled(self.is_open)
        self.btn_get_params.setEnabled(self.is_open)
        self.btn_set_params.setEnabled(self.is_open)
    
    def _control_ui_loop(self):
        """Цикл обработки команд управления видимостью UI"""
        while not self.queue_manager.stop_event.is_set():
            try:
                command = self.queue_manager.control_ui.get(timeout=0.1)
                if command:
                    cmd_type = command.get('type')
                    if cmd_type == 'show':
                        self.show()
                    elif cmd_type == 'hide':
                        self.hide()
                    elif cmd_type == 'toggle':
                        if self.isVisible():
                            self.hide()
                        else:
                            self.show()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in control UI loop: {e}")
    
    def show(self):
        """Показать окно и возобновить обновление кадров если нужно"""
        super().show()
        # Если таймер был запущен до скрытия, возобновляем его
        if self.frame_timer_was_running and self.is_grabbing:
            self.frame_timer.start(16)
            self.frame_timer_was_running = False
            print("UI SDK: Frame timer resumed")
    
    def hide(self):
        """Скрыть окно и остановить обновление кадров для экономии ресурсов"""
        # Сохраняем состояние таймера перед скрытием
        if self.frame_timer.isActive():
            self.frame_timer_was_running = True
            self.frame_timer.stop()
            print("UI SDK: Frame timer stopped (window hidden)")
        super().hide()
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        print("Closing UI...")
        
        # Останавливаем захват и закрываем камеру
        if self.is_grabbing:
            self.stop_grabbing()
        
        if self.is_open:
            self.close_camera()
        
        # Останавливаем поток сообщений
        self.message_thread.stop()
        
        # Останавливаем поток управления UI
        if hasattr(self, 'control_ui_thread'):
            self.queue_manager.stop_event.set()
        
        # Отправляем команду завершения процесса камеры
        self.queue_manager.ui_to_camera.put({
            'type': 'shutdown'
        })
        
        event.accept()
        print("UI closed")


def main(queue_manager=None):
    """Главная функция UI процесса"""
    app = QApplication(sys.argv)
    
    print("="*60)
    print("Independent Camera Processes")
    print("="*60)
    print("UI and Camera are separate processes")
    print("Communication via QueueManager")
    print("="*60)
    
    window = CameraUI(
                    queue_manager=queue_manager, 
                    )
    
    # По умолчанию окно скрыто
    window.hide()
    
    sys.exit(app.exec_())
