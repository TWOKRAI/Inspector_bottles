from PyQt5.QtWidgets import QWidget, QVBoxLayout
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl


class RobotWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_robot=None, callback=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_robot = controls_robot
        self.callback = callback
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        checkbox_control = CheckboxControl(
            "robot_on", 
            False, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl(
            "capture", 
            False, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(checkbox_control)

        slider_control = SliderControl(
            "position", 
            0, 
            3, 
            0, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "shift_time", 
            0, 
            2000, 
            1760, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            min_access=2, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "shift", 
            0, 
            1000, 
            0, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "lenght", 
            0, 
            200, 
            0, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "back", 
            -200, 
            200, 
            0, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "pr", 
            600, 
            1400, 
            1130, 
            transfer_k=0.001, 
            round_k=3, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "tracking", 
            0, 
            800, 
            50, 
            transfer_k=1, 
            round_k=0, 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl(
            "do1", 
            False, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl(
            "do2", 
            False, 
            "left", 
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(checkbox_control)

        slider_control = SliderControl(
            "min_rob_x", 
            50, 
            590,
            78,
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "max_rob_x", 
            50, 
            590,
            488,
            ui_elements=self.ui_elements, 
            controls=self.controls_robot, 
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        return dict(self.controls_robot) if self.controls_robot else {}
    
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
