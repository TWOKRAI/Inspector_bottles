from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGroupBox
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from queue import Empty
from App.Components.slider import SliderControl


class VisualSettingsWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls=None, callback=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls = controls
        self.callback = callback
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        layout.addWidget(QLabel("Масштаб окна изображения (меньше = больше места для регуляторов):"))
        
        scale_slider = SliderControl(
            "image_scale", 
            20, 
            100, 
            50, 
            transfer_k=0.01, 
            round_k=2,
            ui_elements=self.ui_elements, 
            controls=self.controls,
            callback=self._on_visual_scale_changed, 
            parent=self
        )
        layout.addWidget(scale_slider)
        
        self.visual_scale_label = QLabel("Масштаб: 0.50")
        layout.addWidget(self.visual_scale_label)
        
        # Группа для отладочного логирования
        debug_group = QGroupBox("Отладочное логирование")
        debug_layout = QVBoxLayout()
        debug_group.setLayout(debug_layout)
        
        # Описание
        info_label = QLabel("Логирует один кадр обработки и создает Markdown отчет\nс изображениями всех этапов")
        info_label.setWordWrap(True)
        debug_layout.addWidget(info_label)
        
        # Кнопка "Записать кадр и создать отчет"
        self.generate_report_button = QPushButton("📝 Записать кадр и создать отчет")
        self.generate_report_button.clicked.connect(self._on_generate_report_clicked)
        self.generate_report_button.setMinimumHeight(40)
        debug_layout.addWidget(self.generate_report_button)
        
        # Информация о сохранении
        self.status_label = QLabel("Готов к записи")
        self.status_label.setWordWrap(True)
        debug_layout.addWidget(self.status_label)
        
        # Кнопка для открытия папки с отчетами
        self.open_folder_button = QPushButton("📂 Открыть папку с отчетами")
        self.open_folder_button.clicked.connect(self._on_open_folder_clicked)
        debug_layout.addWidget(self.open_folder_button)
        
        layout.addWidget(debug_group)
    
    def _on_visual_scale_changed(self):
        if self.controls:
            scale = self.controls.get('image_scale', 0.5)
            if hasattr(self, 'visual_scale_label'):
                self.visual_scale_label.setText(f"Масштаб: {scale:.2f}")
        if self.callback:
            self.callback()
    
    def get_params(self):
        """Возвращает словарь параметров этого виджета для сохранения/загрузки рецептов"""
        return dict(self.controls) if self.controls else {}
    
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
                        # Обновляем label
                        if param_name == 'image_scale':
                            scale = self.controls.get('image_scale', 0.5) if self.controls else 0.5
                            if hasattr(self, 'visual_scale_label'):
                                self.visual_scale_label.setText(f"Масштаб: {scale:.2f}")
                except Exception as e:
                    print(f"Ошибка установки значения для {param_name}: {e}")
    
    
    def _get_current_frame_id(self):
        """Получает frame_id из последнего кадра в display_queue"""
        if not self.window_manager or not hasattr(self.window_manager, 'queue_manager'):
            return None
        
        try:
            last_frame = None
            display_queue = self.window_manager.queue_manager.display_queue
            
            # Получаем последний кадр из очереди
            while not display_queue.empty():
                try:
                    last_frame = display_queue.get_nowait()
                except:
                    break
            
            frame_id = None
            if last_frame and 'frame_id' in last_frame:
                frame_id = last_frame['frame_id']
            else:
                # Если не удалось получить, используем текущее время
                import time
                frame_id = int(time.time() * 1000)
            
            # Возвращаем кадр обратно в очередь если он был извлечен
            if last_frame:
                try:
                    display_queue.put_nowait(last_frame)
                except:
                    pass
            
            return frame_id
        except Exception as e:
            print(f"Ошибка получения frame_id: {e}")
            import time
            return int(time.time() * 1000)  # Fallback
    
    def _on_generate_report_clicked(self):
        """Обработчик нажатия кнопки 'Записать кадр и создать отчет'"""
        if not self.window_manager or not hasattr(self.window_manager, 'queue_manager'):
            self.status_label.setText("❌ Ошибка: нет доступа к queue_manager")
            return
        
        try:
            # Обновляем статус
            self.status_label.setText("⏳ Получение кадра...")
            self.generate_report_button.setEnabled(False)
            
            # Используем фиксированный frame_id для одного кадра
            # Всегда перезаписываем один и тот же кадр
            frame_id = "current_frame"  # Фиксированный ID для одного кадра
            
            # Очищаем очередь управления перед отправкой команд
            control_queue = self.window_manager.queue_manager.control_debug_logger
            while not control_queue.empty():
                try:
                    control_queue.get_nowait()
                except:
                    break
            
            # Отправляем команду генерации отчета
            # Процесс логгера установит маркеры для всех процессов
            control_queue.put({
                'command': 'generate_report'
            })
            
            self.status_label.setText("📹 Ожидание обработки кадра...")
            print("Debug logger: Sent command to generate report with markers")
            
            # Ждем завершения обработки и автоматически обновляем статус
            from PyQt5.QtCore import QTimer
            
            def check_report_status():
                # Проверяем статус через очередь
                try:
                    control = self.window_manager.queue_manager.control_debug_logger.get_nowait()
                    if control.get('command') == 'report_generated':
                        report_path = control.get('report_path')
                        self.status_label.setText(f"✅ Отчет создан\n📄 {report_path}")
                        self.generate_report_button.setEnabled(True)
                        return
                except Empty:
                    pass
                
                # Если отчет еще не готов, проверяем еще раз через 0.5 секунды
                QTimer.singleShot(500, check_report_status)
            
            # Начинаем проверку статуса через 1 секунду
            QTimer.singleShot(1000, check_report_status)
            
            # Таймаут на случай если отчет не будет сгенерирован
            def timeout_handler():
                if not self.generate_report_button.isEnabled():
                    self.status_label.setText("⏱ Таймаут ожидания отчета")
                    self.generate_report_button.setEnabled(True)
            
            QTimer.singleShot(10000, timeout_handler)  # 10 секунд таймаут
            
        except Exception as e:
            self.status_label.setText(f"❌ Ошибка: {str(e)}")
            self.generate_report_button.setEnabled(True)
            print(f"Ошибка создания отчета: {e}")
    
    def _on_open_folder_clicked(self):
        """Открывает папку с отчетами в проводнике"""
        import os
        try:
            # Получаем абсолютный путь к папке с отчетами
            base_dir = os.path.join(os.path.dirname(__file__), '../../../Data/debug_logs')
            base_dir = os.path.abspath(base_dir)
            
            # Создаем папку если её нет
            os.makedirs(base_dir, exist_ok=True)
            
            # Открываем папку в проводнике
            QDesktopServices.openUrl(QUrl.fromLocalFile(base_dir))
            self.status_label.setText(f"📂 Открыта папка:\n{base_dir}")
        except Exception as e:
            self.status_label.setText(f"❌ Ошибка открытия папки: {str(e)}")
            print(f"Ошибка открытия папки с отчетами: {e}")
