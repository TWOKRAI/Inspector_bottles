from PyQt5.QtWidgets import QWidget, QVBoxLayout
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl


class NeurounWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls=None, controls_neuroun=None, controls_draw=None, callback=None, callback_neuroun=None, callback_draw=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls = controls
        self.controls_neuroun = controls_neuroun
        self.controls_draw = controls_draw
        self.callback = callback
        self.callback_neuroun = callback_neuroun
        self.callback_draw = callback_draw
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        checkbox_control = CheckboxControl(
            "neuroun", 
            True, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=self.controls_neuroun, 
            callback=self.callback_neuroun, 
            parent=self
        )
        layout.addWidget(checkbox_control)

        slider_control = SliderControl(
            "predict", 
            0, 
            100, 
            43, 
            transfer_k=0.01, 
            round_k=2, 
            ui_elements=self.ui_elements, 
            controls=self.controls_neuroun, 
            callback=self.callback_neuroun, 
            parent=self
        )
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl(
            "find_object", 
            True, 
            "left", 
            ui_elements=self.ui_elements,
            controls=self.controls_neuroun, 
            callback=self.callback_neuroun, 
            parent=self
        )
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl(
            "find_object_train", 
            False, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=[self.controls, self.controls_neuroun] if (self.controls and self.controls_neuroun) else (self.controls_neuroun if self.controls_neuroun else []), 
            callback=[self.callback, self.callback_neuroun] if (self.callback and self.callback_neuroun) else (self.callback_neuroun if self.callback_neuroun else []),
            parent=self
        )
        layout.addWidget(checkbox_control)
        
        checkbox_control = CheckboxControl(
            "save_image_brak", 
            True, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [],
            callback=[self.callback_draw] if self.callback_draw else [],
            parent=self
        )
        layout.addWidget(checkbox_control)
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        all_params = {}
        if self.controls:
            all_params.update(self.controls)
        if self.controls_neuroun:
            all_params.update(self.controls_neuroun)
        if self.controls_draw:
            all_params.update(self.controls_draw)
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
