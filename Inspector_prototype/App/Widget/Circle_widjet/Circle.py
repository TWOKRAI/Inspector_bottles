from PyQt5.QtWidgets import QWidget, QVBoxLayout
from App.Components.slider import SliderControl


class CircleWidget(QWidget):
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

        slider_control = SliderControl(
            "dp", 
            0, 
            20, 
            14, 
            transfer_k=0.1, 
            round_k=1, 
            min_access=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "minDist", 
            0, 
            100, 
            51, 
            min_access=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "param1", 
            0, 
            200, 
            47, 
            min_access=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "param2", 
            0, 
            200, 
            31, 
            min_access=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "minRadius", 
            0, 
            100, 
            22, 
            min_access=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "maxRadius", 
            0, 
            100, 
            41, 
            min_access=1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)
    
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
                except Exception as e:
                    print(f"Ошибка установки значения для {param_name}: {e}")
