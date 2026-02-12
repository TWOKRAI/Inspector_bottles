from PyQt5.QtWidgets import QWidget, QVBoxLayout
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl


class ProcessingWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_processing=None, callback=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_processing = controls_processing
        self.callback = callback
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Чекбокс включения обработки
        checkbox_control = CheckboxControl(
            "enable_processing", 
            False, 
            "left",
            ui_elements=self.ui_elements, 
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(checkbox_control)
        
        # Чекбокс показа маски
        checkbox_control = CheckboxControl(
            "show_mask", 
            False, 
            "left",
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(checkbox_control)
        
        # Чекбокс переключения между оригиналом и обработанным
        checkbox_control = CheckboxControl(
            "show_processed", 
            False, 
            "left",
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(checkbox_control)
        
        # Регуляторы размера окна изображения
        slider_control = SliderControl(
            "image_width", 
            200, 
            2000, 
            1024,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "image_height", 
            200, 
            2000, 
            780,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        # Регуляторы обрезки изображения (максимальные значения будут обновляться при получении размера)
        self.crop_top_slider = SliderControl(
            "crop_top", 
            0, 
            2160, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_top_slider)
        
        self.crop_bottom_slider = SliderControl(
            "crop_bottom", 
            0, 
            2160, 
            2160,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_bottom_slider)
        
        self.crop_left_slider = SliderControl(
            "crop_left", 
            0, 
            3840, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_left_slider)
        
        self.crop_right_slider = SliderControl(
            "crop_right", 
            0, 
            3840, 
            3840,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_right_slider)
        
        # Регуляторы HSV нижней границы
        slider_control = SliderControl(
            "hl", 
            0, 
            179, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "sl", 
            0, 
            255, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "vl", 
            0, 
            255, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        # Регуляторы HSV верхней границы
        slider_control = SliderControl(
            "hm", 
            0, 
            179, 
            179,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "sm", 
            0, 
            255, 
            255,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "vm", 
            0, 
            255, 
            255,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
    
    def update_image_size(self, width, height):
        """Обновляет максимальные значения слайдеров обрезки при получении размера изображения"""
        if hasattr(self, 'crop_top_slider') and height > 0:
            self.crop_top_slider.slider.setMaximum(height)
        if hasattr(self, 'crop_bottom_slider') and height > 0:
            self.crop_bottom_slider.slider.setMaximum(height)
            if self.controls_processing.get('crop_bottom', 0) == 0 or self.controls_processing.get('crop_bottom', 0) > height:
                self.controls_processing['crop_bottom'] = height
                self.crop_bottom_slider.slider.setValue(height)
        if hasattr(self, 'crop_left_slider') and width > 0:
            self.crop_left_slider.slider.setMaximum(width)
        if hasattr(self, 'crop_right_slider') and width > 0:
            self.crop_right_slider.slider.setMaximum(width)
            if self.controls_processing.get('crop_right', 0) == 0 or self.controls_processing.get('crop_right', 0) > width:
                self.controls_processing['crop_right'] = width
                self.crop_right_slider.slider.setValue(width)
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        return dict(self.controls_processing) if self.controls_processing else {}
    
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
                    from PyQt5.QtWidgets import QSlider, QCheckBox
                    if isinstance(element, QSlider):
                        value = float(param_value)
                        value = value / transfer_k
                        element.setValue(int(round(value)))
                    elif isinstance(element, QCheckBox):
                        value = str(param_value).lower() in ['true', '1', 'yes']
                        element.setChecked(value)
                except Exception as e:
                    print(f"Ошибка установки значения для {param_name}: {e}")
