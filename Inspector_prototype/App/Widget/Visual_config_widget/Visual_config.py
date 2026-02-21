# -*- coding: utf-8 -*-
"""
Виджет конфигурации визуальных настроек приложения.
Отвечает только за конфигурацию визуальных параметров.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QSpinBox, QMessageBox
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl


class VisualConfigWidget(QWidget):
    """Виджет для настройки визуальных параметров приложения"""
    
    def __init__(self, window_manager=None, ui_elements=None, controls=None, callback=None, app_config=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls = controls
        self.callback = callback
        self.app_config = app_config  # Менеджер конфигурации приложения
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Масштаб изображения
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
        
        # Группа настроек ограничения размера окна при fullscreen
        fullscreen_limit_group = QGroupBox("Ограничение размера окна при режиме 'ЭКРАН'")
        fullscreen_limit_layout = QVBoxLayout()
        fullscreen_limit_group.setLayout(fullscreen_limit_layout)
        
        # Чекбокс для включения ограничения
        limit_fullhd_label = QLabel("Ограничить размер окна при включении режима 'ЭКРАН'")
        limit_fullhd_label.setWordWrap(True)
        fullscreen_limit_layout.addWidget(limit_fullhd_label)
        
        # Используем конфигурацию приложения вместо controls_visual
        if self.app_config:
            initial_limit = self.app_config.get_limit_fullhd()
        else:
            initial_limit = False
        
        # Создаем временный словарь для чекбокса, так как значение хранится в app_config
        self._temp_controls = {'limit_fullhd': initial_limit}
        self.limit_fullhd_checkbox = CheckboxControl(
            "limit_fullhd",
            initial_limit,
            "left",
            ui_elements=self.ui_elements,
            controls=self._temp_controls,
            callback=self._on_limit_fullhd_changed,
            parent=self
        )
        fullscreen_limit_layout.addWidget(self.limit_fullhd_checkbox)
        
        # Поля для ширины и высоты
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Ширина:"))
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(800, 7680)
        self.width_spinbox.setValue(self.app_config.get_fullscreen_limit_width() if self.app_config else 1920)
        self.width_spinbox.valueChanged.connect(self._on_size_changed)
        size_layout.addWidget(self.width_spinbox)
        
        size_layout.addWidget(QLabel("Высота:"))
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(600, 4320)
        self.height_spinbox.setValue(self.app_config.get_fullscreen_limit_height() if self.app_config else 1080)
        self.height_spinbox.valueChanged.connect(self._on_size_changed)
        size_layout.addWidget(self.height_spinbox)
        
        fullscreen_limit_layout.addLayout(size_layout)
        
        # Кнопки для сохранения и загрузки конфигурации
        config_buttons_layout = QHBoxLayout()
        btn_save_config = QPushButton("💾 Сохранить конфигурацию")
        btn_save_config.clicked.connect(self._on_save_config)
        btn_save_config.setMinimumHeight(40)
        config_buttons_layout.addWidget(btn_save_config)
        
        btn_load_config = QPushButton("📂 Загрузить конфигурацию")
        btn_load_config.clicked.connect(self._on_load_config)
        btn_load_config.setMinimumHeight(40)
        config_buttons_layout.addWidget(btn_load_config)
        
        btn_reset_config = QPushButton("🔄 Сбросить к умолчанию")
        btn_reset_config.clicked.connect(self._on_reset_config)
        btn_reset_config.setMinimumHeight(40)
        config_buttons_layout.addWidget(btn_reset_config)
        
        fullscreen_limit_layout.addLayout(config_buttons_layout)
        
        # Информация о файле конфигурации
        if self.app_config:
            config_info_label = QLabel(f"Файл конфигурации: {self.app_config.config_file_path}")
            config_info_label.setWordWrap(True)
            config_info_label.setStyleSheet("color: gray; font-size: 10px;")
            fullscreen_limit_layout.addWidget(config_info_label)
        
        layout.addWidget(fullscreen_limit_group)
    
    def _on_visual_scale_changed(self):
        """Обработчик изменения масштаба изображения"""
        if self.controls:
            scale = self.controls.get('image_scale', 0.5)
            if hasattr(self, 'visual_scale_label'):
                self.visual_scale_label.setText(f"Масштаб: {scale:.2f}")
        if self.callback:
            self.callback()
    
    def _on_limit_fullhd_changed(self):
        """Обработчик изменения чекбокса ограничения размера окна"""
        if self.app_config:
            limit_fullhd = self._temp_controls.get('limit_fullhd', False)
            self.app_config.set_limit_fullhd(limit_fullhd)
            
            # Применяем ограничение сразу при изменении, если fullscreen уже включен
            if self.window_manager and self.window_manager.fullscreen:
                # Переприменяем fullscreen с учетом нового состояния ограничения
                self.window_manager.set_fullscreen(True)
        if self.callback:
            self.callback()
    
    def _on_size_changed(self):
        """Обработчик изменения ширины или высоты"""
        if self.app_config:
            width = self.width_spinbox.value()
            height = self.height_spinbox.value()
            self.app_config.set_fullscreen_limit_size(width, height)
            
            # Применяем новый размер сразу, если fullscreen уже включен и ограничение активно
            if self.window_manager and self.window_manager.fullscreen:
                if self.app_config.get_limit_fullhd():
                    self.window_manager.set_fullscreen(True)
    
    def _on_save_config(self):
        """Сохранить конфигурацию приложения"""
        if self.app_config:
            self.app_config._save_config()
            QMessageBox.information(self, "Успех", f"Конфигурация сохранена в:\n{self.app_config.config_file_path}")
    
    def _on_load_config(self):
        """Загрузить конфигурацию приложения"""
        if self.app_config:
            self.app_config._load_config()
            # Обновляем UI с загруженными значениями
            self._refresh_config_ui()
            QMessageBox.information(self, "Успех", "Конфигурация загружена из файла")
    
    def _on_reset_config(self):
        """Сбросить конфигурацию к значениям по умолчанию"""
        if self.app_config:
            reply = QMessageBox.question(
                self, "Подтверждение",
                "Вы уверены, что хотите сбросить конфигурацию к значениям по умолчанию?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.app_config.reset_to_defaults()
                self._refresh_config_ui()
                # Применяем изменения если fullscreen включен
                if self.window_manager and self.window_manager.fullscreen:
                    self.window_manager.set_fullscreen(True)
                QMessageBox.information(self, "Успех", "Конфигурация сброшена к значениям по умолчанию")
    
    def _refresh_config_ui(self):
        """Обновить UI с текущими значениями из конфигурации"""
        if self.app_config:
            # Обновляем чекбокс
            limit_fullhd = self.app_config.get_limit_fullhd()
            self._temp_controls['limit_fullhd'] = limit_fullhd
            if hasattr(self, 'limit_fullhd_checkbox'):
                self.limit_fullhd_checkbox.checkbox.blockSignals(True)
                self.limit_fullhd_checkbox.checkbox.setChecked(limit_fullhd)
                self.limit_fullhd_checkbox.checkbox.blockSignals(False)
            
            # Обновляем поля ширины и высоты
            if hasattr(self, 'width_spinbox'):
                self.width_spinbox.blockSignals(True)
                self.width_spinbox.setValue(self.app_config.get_fullscreen_limit_width())
                self.width_spinbox.blockSignals(False)
            
            if hasattr(self, 'height_spinbox'):
                self.height_spinbox.blockSignals(True)
                self.height_spinbox.setValue(self.app_config.get_fullscreen_limit_height())
                self.height_spinbox.blockSignals(False)
    
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
