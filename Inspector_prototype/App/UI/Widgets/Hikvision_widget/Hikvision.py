from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox)
from App.Components.slider import SliderControl
from App.Components.structured_table import StructuredTableWidget
from App.Widget.Hikvision_widjet.Threads.thread_camera_message import CameraMessageThread


class HikvisionWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_hikvision=None, callback=None,
                 controls_camera=None, callback_camera=None, stop_event=None, data_manager=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_hikvision = controls_hikvision
        self.callback = callback
        self.controls_camera = controls_camera or {}
        self.callback_camera = callback_camera
        self.stop_event = stop_event
        self.data_manager = data_manager  # DataManager для автоматического создания камер
        
        self.fps_sdk = 0.0
        self.fps_after_processing = 0.0
        self.processing_time_ms = 0.0
        self.total_time_ms = 0.0
        self.image_height = 0
        self.image_width = 0
        self.hikvision_device_list = []
        self._current_device_index = -1
        self._current_source = "image"
        self.camera_message_thread = None

        self.init_ui()
        self.start_camera_message_thread()
        
        # Подключаем сигналы DataManager для синхронизации списка камер
        if self.data_manager:
            self.data_manager.camera_changed.connect(self._on_data_camera_changed)
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Источник кадров: таблица (камеры + изображение)
        source_group = QGroupBox("Источник кадров")
        source_layout = QVBoxLayout()
        enum_row = QHBoxLayout()
        btn_enum = QPushButton("Enum Devices")
        btn_enum.setMinimumHeight(36)
        btn_enum.setMinimumWidth(140)
        btn_enum.clicked.connect(self.sdk_enum_devices)
        enum_row.addWidget(btn_enum)
        enum_row.addStretch()
        source_layout.addLayout(enum_row)
        
        # Выпадающий список для выбора активной камеры (синхронизируется с DataManager)
        if self.data_manager:
            camera_select_row = QHBoxLayout()
            camera_select_row.addWidget(QLabel("Активная камера:"))
            self.camera_combo = QComboBox()
            self.camera_combo.currentIndexChanged.connect(self._on_camera_combo_changed)
            camera_select_row.addWidget(self.camera_combo, 1)
            source_layout.addLayout(camera_select_row)
            self._refresh_camera_combo()
        
        self.sources_table = StructuredTableWidget(
            columns=[
                {"key": "name", "label": "Название", "type": "text"},
                {"key": "enabled", "label": "Вкл.", "type": "checkbox"},
                {"key": "process", "label": "Процесс", "type": "text"},
                {"key": "state", "label": "Состояние", "type": "text"},
                {"key": "ip", "label": "IP", "type": "text"},
            ],
            parent=self
        )
        self.sources_table.row_selected.connect(self._on_source_row_selected)
        self.sources_table.cell_changed.connect(self._on_source_cell_changed)
        source_layout.addWidget(self.sources_table)
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        self._refresh_sources_table()
        self.sources_table.setCurrentCell(0, 0)
        self._on_source_row_selected(0)

        # Кнопки Open и Close на одном уровне
        camera_buttons_layout = QHBoxLayout()
        btn_open = QPushButton("Open Camera")
        btn_open.setMinimumHeight(40)
        btn_open.clicked.connect(self.sdk_open_camera)
        camera_buttons_layout.addWidget(btn_open)
        
        btn_close = QPushButton("Close Camera")
        btn_close.setMinimumHeight(40)
        btn_close.clicked.connect(self.sdk_close_camera)
        camera_buttons_layout.addWidget(btn_close)
        layout.addLayout(camera_buttons_layout)
        
        # Кнопки Start и Stop Grabbing ниже
        grabbing_buttons_layout = QHBoxLayout()
        btn_start = QPushButton("Start Grabbing")
        btn_start.setMinimumHeight(40)
        btn_start.clicked.connect(self.sdk_start_grabbing)
        grabbing_buttons_layout.addWidget(btn_start)
        
        btn_stop = QPushButton("Stop Grabbing")
        btn_stop.setMinimumHeight(40)
        btn_stop.clicked.connect(self.sdk_stop_grabbing)
        grabbing_buttons_layout.addWidget(btn_stop)
        layout.addLayout(grabbing_buttons_layout)
        
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
        params_buttons_layout = QHBoxLayout()
        btn_get_params = QPushButton("Обновить")  # Переименовано из Get Parameters
        btn_get_params.setMinimumHeight(40)
        btn_get_params.clicked.connect(self.sdk_get_parameters)
        params_buttons_layout.addWidget(btn_get_params)
        
        btn_set_params = QPushButton("Set Parameters")
        btn_set_params.setMinimumHeight(40)
        btn_set_params.clicked.connect(self.sdk_set_parameters)
        params_buttons_layout.addWidget(btn_set_params)
        layout.addLayout(params_buttons_layout)
        
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
        
        # Кнопки показа/скрытия UI SDK окна (внизу на одном уровне)
        sdk_buttons_layout = QHBoxLayout()
        btn_show_ui = QPushButton("Показать UI SDK")
        btn_show_ui.setMinimumHeight(50)
        btn_show_ui.clicked.connect(lambda: self.toggle_sdk_ui(True))
        sdk_buttons_layout.addWidget(btn_show_ui)
        
        btn_hide_ui = QPushButton("Скрыть UI SDK")
        btn_hide_ui.setMinimumHeight(50)
        btn_hide_ui.clicked.connect(lambda: self.toggle_sdk_ui(False))
        sdk_buttons_layout.addWidget(btn_hide_ui)
        layout.addLayout(sdk_buttons_layout)
    
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
            self._refresh_sources_table()
            # Автоматически создаем камеры в DataManager при обнаружении
            if self.data_manager:
                self._create_cameras_in_datamanager(devices)
        
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
        """Открыть камеру (используется выбранная строка в таблице источников)."""
        if self._current_source == "image":
            return
        if self.window_manager and hasattr(self.window_manager, 'queue_manager'):
            try:
                real_camera_index = self._current_device_index
                if len(self.hikvision_device_list) > 0 and real_camera_index < 0:
                    real_camera_index = self.hikvision_device_list[0].get('index', 0)
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
    
    def _refresh_sources_table(self):
        """Обновить таблицу источников: Изображение + список камер."""
        rows = [
            {"name": "Изображение", "enabled": True, "process": "Процесс 1", "state": "-", "ip": "-",
             "_source": "image", "_device_index": -1}
        ]
        for i, dev in enumerate(self.hikvision_device_list):
            idx = dev.get("index", i)
            name = dev.get("display_name", f"Camera {idx}")
            ip = dev.get("ip", dev.get("serial", "-"))
            rows.append({
                "name": name, "enabled": True, "process": "Процесс 1",
                "state": "—", "ip": str(ip),
                "_source": "camera", "_device_index": idx
            })
        self.sources_table.set_data(rows)

    def _on_source_row_selected(self, row_index):
        """Выбор строки источника: установить source и обновить панель ниже."""
        row = self.sources_table.get_row_data(row_index) if row_index >= 0 else None
        if not row:
            return
        self._current_source = row.get("_source", "camera")
        self._current_device_index = row.get("_device_index", 0)
        self.controls_camera["source"] = self._current_source
        if self.callback_camera:
            self.callback_camera()
        if self._current_source == "camera" and self._current_device_index >= 0:
            import threading
            def delayed():
                import time
                time.sleep(0.3)
                self.sdk_get_parameters()
            threading.Thread(target=delayed, daemon=True).start()

    def _on_source_cell_changed(self, row_index, column_key, value):
        """Изменение ячейки (например Вкл.) — можно синхронизировать с процессами."""
        pass

    def showEvent(self, event):
        """При показе виджета (переходе во вкладку) автоматически получаем параметры"""
        super().showEvent(event)
        if getattr(self, '_current_source', None) == 'camera' and getattr(self, '_current_device_index', -1) >= 0:
            import threading
            def delayed_get_params():
                import time
                time.sleep(0.2)
                self.sdk_get_parameters()
            threading.Thread(target=delayed_get_params, daemon=True).start()
    
    def stop_thread(self):
        """Остановить поток сообщений камеры"""
        if self.camera_message_thread:
            self.camera_message_thread.stop()
    
    def _create_cameras_in_datamanager(self, devices):
        """Автоматически создавать камеры в DataManager при обнаружении через Enum Devices"""
        if not self.data_manager:
            return
        
        for dev in devices:
            device_index = dev.get("index", -1)
            if device_index < 0:
                continue
            
            # Генерируем ID камеры на основе индекса устройства
            camera_id = f"camera_{device_index}"
            
            # Проверяем, существует ли уже камера с таким ID
            if camera_id not in self.data_manager.get_cameras():
                # Получаем имя камеры из устройства
                camera_name = dev.get("display_name", f"Camera {device_index}")
                ip = dev.get("ip", dev.get("serial", ""))
                
                # Создаем камеру в DataManager
                created_id = self.data_manager.add_camera(camera_id=camera_id, name=camera_name)
                if created_id:
                    print(f"HikvisionWidget: Автоматически создана камера '{camera_name}' (ID: {created_id}) в DataManager")
                    # Сохраняем параметры Hikvision если есть
                    hikvision_params = {
                        "Frame Rate": 0.0,
                        "Exposure": 0,
                        "Gain": 0.0
                    }
                    self.data_manager.set_camera_hikvision_params(created_id, hikvision_params)
        
        # Обновляем выпадающий список камер
        self._refresh_camera_combo()
    
    def _refresh_camera_combo(self):
        """Обновить выпадающий список камер из DataManager"""
        if not self.data_manager or not hasattr(self, 'camera_combo'):
            return
        
        current_camera_id = self.data_manager.get_current_camera_id()
        
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        
        cameras = self.data_manager.get_cameras()
        for camera_id in cameras:
            camera = self.data_manager.get_camera(camera_id)
            camera_name = camera.get("name", camera_id)
            self.camera_combo.addItem(camera_name, camera_id)
        
        # Устанавливаем текущую камеру
        if current_camera_id:
            cameras = self.data_manager.get_cameras()
            if current_camera_id in cameras:
                index = cameras.index(current_camera_id)
                self.camera_combo.setCurrentIndex(index)
        
        self.camera_combo.blockSignals(False)
    
    def _on_camera_combo_changed(self, index):
        """Обработчик изменения выбранной камеры в выпадающем списке"""
        if not self.data_manager or not hasattr(self, 'camera_combo'):
            return
        
        camera_id = self.camera_combo.itemData(index)
        if camera_id:
            self.data_manager.set_current_camera(camera_id)
            print(f"HikvisionWidget: Выбрана камера '{self.camera_combo.itemText(index)}' (ID: {camera_id})")
    
    def _on_data_camera_changed(self, camera_id):
        """Обработчик изменения камеры в DataManager"""
        self._refresh_camera_combo()