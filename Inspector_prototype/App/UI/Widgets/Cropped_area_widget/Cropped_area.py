from PyQt5.QtWidgets import QWidget, QVBoxLayout
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl


class CroppedAreaWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls=None, controls_draw=None, controls_conveyor=None, callback=None, callback_draw=None, callback_conveyor=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls = controls
        self.controls_draw = controls_draw
        self.controls_conveyor = controls_conveyor
        self.callback = callback
        self.callback_draw = callback_draw
        self.callback_conveyor = callback_conveyor
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        checkbox_control = CheckboxControl(
            "camera_robot", 
            False, 
            "top", 
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [], 
            callback=[self.callback_draw] if self.callback_draw else [], 
            parent=self
        )
        layout.addWidget(checkbox_control)

        slider_control = SliderControl(
            "history", 
            0, 
            120, 
            120, 
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [], 
            callback=[self.callback_draw] if self.callback_draw else [], 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "height", 
            0, 
            600, 
            250, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "y_delta", 
            0, 
            100, 
            31, 
            ui_elements=self.ui_elements, 
            controls=[self.controls, self.controls_draw] if (self.controls and self.controls_draw) else (self.controls if self.controls else []), 
            callback=[self.callback, self.callback_draw] if (self.callback and self.callback_draw) else (self.callback if self.callback else []), 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "x_delta", 
            0, 
            100, 
            21, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "x_min", 
            0, 
            1280, 
            150, 
            ui_elements=self.ui_elements, 
            controls=[self.controls, self.controls_draw] if (self.controls and self.controls_draw) else (self.controls if self.controls else []), 
            callback=[self.callback, self.callback_draw] if (self.callback and self.callback_draw) else (self.callback if self.callback else []), 
            parent=self, 
            label='Минимальный Х'
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "x_max", 
            0, 
            1280, 
            730, 
            ui_elements=self.ui_elements, 
            controls=[self.controls, self.controls_draw] if (self.controls and self.controls_draw) else (self.controls if self.controls else []), 
            callback=[self.callback, self.callback_draw] if (self.callback and self.callback_draw) else (self.callback if self.callback else []), 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "conveyor_freq", 
            1, 
            50, 
            25, 
            ui_elements=self.ui_elements, 
            controls=self.controls_conveyor, 
            callback=self.callback_conveyor, 
            parent=self
        )
        layout.addWidget(slider_control)
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        all_params = {}
        if self.controls:
            all_params.update(self.controls)
        if self.controls_draw:
            all_params.update(self.controls_draw)
        if self.controls_conveyor:
            all_params.update(self.controls_conveyor)
        return all_params
    
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
