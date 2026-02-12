from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox)
from App.Components.slider import SliderControl
from App.Widget.Hikvision_widjet.Threads.thread_camera_message import CameraMessageThread


class HikvisionWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_hikvision=None, callback=None, stop_event=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_hikvision = controls_hikvision
        self.callback = callback
        self.stop_event = stop_event
        
        # Данные для FPS и метрик
        self.fps_sdk = 0.0
        self.fps_after_processing = 0.0
        self.processing_time_ms = 0.0
        self.total_time_ms = 0.0
        self.image_height = 0
        self.image_width = 0
        self.hikvision_device_list = []
        
        self.camera_message_thread = None
        
        self.init_ui()
        self.start_camera_message_thread()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Кнопка Enum Devices и выпадающий список камер рядом
        enum_layout = QHBoxLayout()
        btn_enum = QPushButton("Enum Devices")
        btn_enum.setMinimumHeight(40)
        btn_enum.setMinimumWidth(150)
        btn_enum.clicked.connect(self.sdk_enum_devices)
        enum_layout.addWidget(btn_enum)
        
        # Выпадающий список камер рядом с кнопкой
        camera_label = QLabel("Камера:")
        camera_label.setFixedWidth(60)
        enum_layout.addWidget(camera_label)
        
        self.combo_cameras = QComboBox()
        self.combo_cameras.setMinimumHeight(35)
        enum_layout.addWidget(self.combo_cameras, stretch=1)
        layout.addLayout(enum_layout)
        
        btn_open = QPushButton("Open Camera")
        btn_open.setMinimumHeight(40)
        btn_open.clicked.connect(self.sdk_open_camera)
        layout.addWidget(btn_open)
        
        btn_close = QPushButton("Close Camera")
        btn_close.setMinimumHeight(40)
        btn_close.clicked.connect(self.sdk_close_camera)
        layout.addWidget(btn_close)
        
        btn_start = QPushButton("Start Grabbing")
        btn_start.setMinimumHeight(40)
        btn_start.clicked.connect(self.sdk_start_grabbing)
        layout.addWidget(btn_start)
        
        btn_stop = QPushButton("Stop Grabbing")
        btn_stop.setMinimumHeight(40)
        btn_stop.clicked.connect(self.sdk_stop_grabbing)
        layout.addWidget(btn_stop)
        
        # Регуляторы параметров камеры
        slider_control = SliderControl(
            "Frame Rate", 
            0, 
            100, 
            0, 
            transfer_k=0.1, 
            round_k=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls_hikvision, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "Exposure", 
            0, 
            100000, 
            0, 
            transfer_k=1, 
            round_k=0,
            ui_elements=self.ui_elements, 
            controls=self.controls_hikvision,
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "Gain", 
            0, 
            100, 
            0, 
            transfer_k=0.1, 
            round_k=1,
            ui_elements=self.ui_elements, 
            controls=self.controls_hikvision,
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)
        
        # Кнопки получения/установки параметров
        btn_get_params = QPushButton("Get Parameters")
        btn_get_params.setMinimumHeight(40)
        btn_get_params.clicked.connect(self.sdk_get_parameters)
        layout.addWidget(btn_get_params)
        
        btn_set_params = QPushButton("Set Parameters")
        btn_set_params.setMinimumHeight(40)
        btn_set_params.clicked.connect(self.sdk_set_parameters)
        layout.addWidget(btn_set_params)
        
        # FPS и временная информация
        fps_group = QGroupBox("FPS & Performance")
        fps_layout = QVBoxLayout()
        fps_group.setLayout(fps_layout)
        
        self.fps_sdk_label = QLabel("SDK FPS: 0.0")
        self.fps_sdk_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #3498db;")
        fps_layout.addWidget(self.fps_sdk_label)
        
        self.image_size_label = QLabel("Image Size: 0x0")
        self.image_size_label.setStyleSheet("font-size: 12px; color: #9b59b6;")
        fps_layout.addWidget(self.image_size_label)
        
        self.fps_after_label = QLabel("Display FPS: 0.0")
        self.fps_after_label.setStyleSheet("font-size: 12px; color: #2ecc71;")
        fps_layout.addWidget(self.fps_after_label)
        
        self.processing_time_label = QLabel("Processing: 0.0 ms")
        self.processing_time_label.setStyleSheet("font-size: 12px; color: #e67e22;")
        fps_layout.addWidget(self.processing_time_label)
        
        self.total_time_label = QLabel("Total (capture→display): 0.0 ms")
        self.total_time_label.setStyleSheet("font-size: 12px; color: #e74c3c;")
        fps_layout.addWidget(self.total_time_label)
        
        layout.addWidget(fps_group)
        
        # Кнопки показа/скрытия UI SDK окна (внизу)
        btn_show_ui = QPushButton("Показать UI SDK")
        btn_show_ui.setMinimumHeight(50)
        btn_show_ui.clicked.connect(lambda: self.toggle_sdk_ui(True))
        layout.addWidget(btn_show_ui)
        
        btn_hide_ui = QPushButton("Скрыть UI SDK")
        btn_hide_ui.setMinimumHeight(50)
        btn_hide_ui.clicked.connect(lambda: self.toggle_sdk_ui(False))
        layout.addWidget(btn_hide_ui)
    
    def start_camera_message_thread(self):
        """Запустить поток для получения сообщений от камеры"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager') and self.stop_event:
            self.camera_message_thread = CameraMessageThread(
                self.window_manager.queue_manager, 
                self.stop_event
            )
            self.camera_message_thread.message_received.connect(self.handle_camera_message)
            self.camera_message_thread.start()
    
    def handle_camera_message(self, message):
        """Обработать сообщение от процесса камеры"""
        msg_type = message.get('type')
        print(f"HikvisionWidget received camera message: type={msg_type}, message={message}")
        
        if msg_type == 'enum_devices_response':
            devices = message.get('devices', [])
            self.hikvision_device_list = devices
            print(f"HikvisionWidget: Processing {len(devices)} devices")
            
            # Обновляем выпадающий список
            self.combo_cameras.clear()
            if len(devices) == 0:
                self.combo_cameras.addItem("Устройства не найдены")
            else:
                for device in devices:
                    display_name = device.get('display_name', f"Camera {device.get('index', 0)}")
                    print(f"HikvisionWidget: Adding device to combo: {display_name}")
                    self.combo_cameras.addItem(display_name)
            print(f"HikvisionWidget: combo_cameras now has {self.combo_cameras.count()} items")
        
        elif msg_type == 'parameters_response':
            params = message.get('parameters', {})
            # Обновляем значения в controls_hikvision
            if 'Frame Rate' in self.ui_elements:
                self.controls_hikvision['Frame Rate'] = params.get('frame_rate', 0)
            if 'Exposure' in self.ui_elements:
                self.controls_hikvision['Exposure'] = params.get('exposure_time', 0)
            if 'Gain' in self.ui_elements:
                self.controls_hikvision['Gain'] = params.get('gain', 0)
            # Сохраняем FPS из SDK
            self.fps_sdk = params.get('frame_rate', 0.0)
            self.update_fps_display()
        
        elif msg_type == 'image_size':
            # Обновляем размер изображения
            self.image_height = message.get('height', 0)
            self.image_width = message.get('width', 0)
            self.update_fps_display()
            print(f"HikvisionWidget: Image size updated: {self.image_width}x{self.image_height}")
    
    def update_fps_display(self):
        """Обновить отображение FPS и временных метрик"""
        if hasattr(self, 'fps_sdk_label'):
            self.fps_sdk_label.setText(f"SDK FPS: {self.fps_sdk:.1f}")
        if hasattr(self, 'image_size_label'):
            if self.image_width > 0 and self.image_height > 0:
                self.image_size_label.setText(f"Image Size: {self.image_width}x{self.image_height}")
            else:
                self.image_size_label.setText("Image Size: Not detected")
        if hasattr(self, 'fps_after_label'):
            self.fps_after_label.setText(f"Display FPS: {self.fps_after_processing:.1f}")
        if hasattr(self, 'processing_time_label'):
            self.processing_time_label.setText(f"Processing: {self.processing_time_ms:.1f} ms")
        if hasattr(self, 'total_time_label'):
            self.total_time_label.setText(f"Total (capture→display): {self.total_time_ms:.1f} ms")
    
    def update_fps_metrics(self, fps_after, processing_time, total_time):
        """Обновить метрики FPS из внешнего источника (main_window)"""
        self.fps_after_processing = fps_after
        self.processing_time_ms = processing_time
        self.total_time_ms = total_time
        self.update_fps_display()
    
    def toggle_sdk_ui(self, show):
        """Показать/скрыть UI SDK окно"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                self.window_manager.queue_manager.control_ui.put({'type': 'show' if show else 'hide'})
            except Exception as e:
                print(f"Error toggling SDK UI: {e}")
    
    def sdk_enum_devices(self):
        """Перечислить устройства камеры"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                self.window_manager.queue_manager.ui_to_camera.put({'type': 'enum_devices'})
            except Exception as e:
                print(f"Error enumerating devices: {e}")
    
    def sdk_open_camera(self):
        """Открыть камеру"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                camera_index = self.combo_cameras.currentIndex()
                if camera_index < 0 or camera_index >= len(self.hikvision_device_list):
                    camera_index = 0
                
                if len(self.hikvision_device_list) > 0:
                    selected_device = self.hikvision_device_list[camera_index]
                    real_camera_index = selected_device.get('index', camera_index)
                else:
                    real_camera_index = camera_index
                    
                self.window_manager.queue_manager.ui_to_camera.put({'type': 'open', 'camera_index': real_camera_index})
            except Exception as e:
                print(f"Error opening camera: {e}")
    
    def sdk_close_camera(self):
        """Закрыть камеру"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                self.window_manager.queue_manager.ui_to_camera.put({'type': 'close'})
            except Exception as e:
                print(f"Error closing camera: {e}")
    
    def sdk_start_grabbing(self):
        """Начать захват кадров"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                self.window_manager.queue_manager.ui_to_camera.put({'type': 'start_grabbing'})
                # Автоматически запрашиваем параметры после начала захвата
                import threading
                def delayed_get_params():
                    import time
                    time.sleep(0.5)
                    self.sdk_get_parameters()
                threading.Thread(target=delayed_get_params, daemon=True).start()
            except Exception as e:
                print(f"Error starting grabbing: {e}")
    
    def sdk_stop_grabbing(self):
        """Остановить захват кадров"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                self.window_manager.queue_manager.ui_to_camera.put({'type': 'stop_grabbing'})
            except Exception as e:
                print(f"Error stopping grabbing: {e}")
    
    def sdk_get_parameters(self):
        """Получить параметры камеры"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                self.window_manager.queue_manager.ui_to_camera.put({'type': 'get_parameters'})
            except Exception as e:
                print(f"Error getting parameters: {e}")
    
    def sdk_set_parameters(self):
        """Установить параметры камеры"""
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                frame_rate = self.controls_hikvision.get('Frame Rate', 0)
                exposure = self.controls_hikvision.get('Exposure', 0)
                gain = self.controls_hikvision.get('Gain', 0)
                
                self.window_manager.queue_manager.ui_to_camera.put({
                    'type': 'set_parameters',
                    'frame_rate': frame_rate,
                    'exposure_time': exposure,
                    'gain': gain
                })
            except Exception as e:
                print(f"Error setting parameters: {e}")
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        return dict(self.controls_hikvision) if self.controls_hikvision else {}
    
    def apply_params(self, params_dict):
        """Применяет параметры из словаря к элементам UI виджета"""
        if not params_dict or not self.ui_elements:
            return
        
        for param_name, param_value in params_dict.items():
            if param_name in self.ui_elements:
                element_data = self.ui_elements[param_name]
                element = element_data['element']
                transfer_k = element_data.get('transfer_k', 1)
                
                try:
                    from PyQt5.QtWidgets import QSlider
                    if isinstance(element, QSlider):
                        value = float(param_value)
                        value = value / transfer_k
                        element.setValue(int(round(value)))
                except Exception as e:
                    print(f"Ошибка установки значения для {param_name}: {e}")
    
    def stop_thread(self):
        """Остановить поток сообщений камеры"""
        if self.camera_message_thread:
            self.camera_message_thread.stop()
