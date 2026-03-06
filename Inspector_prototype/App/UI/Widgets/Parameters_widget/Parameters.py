from PyQt5.QtWidgets import QWidget, QVBoxLayout
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl


class ParametersWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls=None, controls_draw=None, controls_robot=None, controls_camera=None, callback=None, callback_draw=None, callback_robot=None, callback_camera=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls = controls
        self.controls_draw = controls_draw
        self.controls_robot = controls_robot
        self.controls_camera = controls_camera
        self.callback = callback
        self.callback_draw = callback_draw
        self.callback_robot = callback_robot
        self.callback_camera = callback_camera
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        slider_control = SliderControl(
            "hl", 
            0, 
            179, 
            0, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "sl", 
            0, 
            255, 
            50, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "vl", 
            0, 
            255, 
            28, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "hm", 
            0, 
            179, 
            179, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
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
            controls=self.controls, 
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
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "mode_image", 
            0, 
            5, 
            0, 
            ui_elements=self.ui_elements, 
            controls=self.controls_draw, 
            callback=self.callback_draw, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "area_threshold", 
            0, 
            5200, 
            140, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "snap_y", 
            0, 
            600, 
            200, 
            ui_elements=self.ui_elements, 
            controls=[self.controls, self.controls_robot, self.controls_draw] if (self.controls and self.controls_robot and self.controls_draw) else (self.controls if self.controls else []), 
            callback=[self.callback, self.callback_robot, self.callback_draw] if (self.callback and self.callback_robot and self.callback_draw) else (self.callback if self.callback else []), 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "shift", 
            0, 
            7000, 
            717, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "shift_y", 
            0, 
            1000, 
            120, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "mode", 
            0, 
            1, 
            1, 
            ui_elements=self.ui_elements, 
            controls=self.controls, 
            callback=self.callback, 
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "fps", 
            1, 
            25, 
            5, 
            ui_elements=self.ui_elements, 
            controls=[self.controls_camera, self.controls_draw] if (self.controls_camera and self.controls_draw) else (self.controls_camera if self.controls_camera else []), 
            callback=[self.callback_camera, self.callback_draw] if (self.callback_camera and self.callback_draw) else (self.callback_camera if self.callback_camera else []), 
            parent=self
        )
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl(
            "calibration_line", 
            False, 
            "top", 
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [], 
            callback=[self.callback_draw] if self.callback_draw else [], 
            parent=self
        )
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl(
            "calibration_circle", 
            False, 
            "top", 
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [], 
            callback=[self.callback_draw] if self.callback_draw else [], 
            parent=self
        )
        layout.addWidget(checkbox_control)

        slider_control = SliderControl(
            "resize_delta", 
            -50, 
            50, 
            0, 
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [], 
            callback=[self.callback_draw] if self.callback_draw else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "blend_alpha", 
            0, 
            100, 
            100, 
            transfer_k=0.01, 
            round_k=2,
            ui_elements=self.ui_elements, 
            controls=[self.controls_draw] if self.controls_draw else [], 
            callback=[self.callback_draw] if self.callback_draw else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "k_size", 
            0, 
            200, 
            115, 
            transfer_k=0.01, 
            round_k=2,
            ui_elements=self.ui_elements, 
            controls=[self.controls] if self.controls else [], 
            callback=[self.callback] if self.callback else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "method_resize", 
            0, 
            4, 
            2, 
            ui_elements=self.ui_elements, 
            controls=[self.controls] if self.controls else [], 
            callback=[self.callback] if self.callback else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "top", 
            0, 
            300, 
            145, 
            ui_elements=self.ui_elements, 
            controls=[self.controls] if self.controls else [], 
            callback=[self.callback] if self.callback else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "bottom", 
            0, 
            1000, 
            535, 
            ui_elements=self.ui_elements, 
            controls=[self.controls] if self.controls else [], 
            callback=[self.callback] if self.callback else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "left", 
            0, 
            500, 
            190, 
            ui_elements=self.ui_elements, 
            controls=[self.controls] if self.controls else [], 
            callback=[self.callback] if self.callback else [],
            parent=self
        )
        layout.addWidget(slider_control)

        slider_control = SliderControl(
            "right", 
            0, 
            1500, 
            1054, 
            ui_elements=self.ui_elements, 
            controls=[self.controls] if self.controls else [], 
            callback=[self.callback] if self.callback else [],
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
        if self.controls_robot:
            all_params.update(self.controls_robot)
        if self.controls_camera:
            all_params.update(self.controls_camera)
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
