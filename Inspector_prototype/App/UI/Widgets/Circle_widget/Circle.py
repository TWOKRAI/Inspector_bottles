from PyQt5.QtWidgets import QWidget, QVBoxLayout
# from App.Components.slider import SliderControl
from App.Components.slider_enhanced import SliderControlEnhanced


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

        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        from App.Registers.models import DrawRegisters

        for field_name in ("dp", "minDist", "param1", "param2", "minRadius", "maxRadius"):
            slider_control = SliderControlEnhanced(
                field=(DrawRegisters, field_name),
                parent=self,
            )
            layout.addWidget(slider_control)
    
    # def get_params(self):
    #     """Возвращает словарь параметров этого виджета для сохранения/загрузки рецептов"""
    #     return dict(self.controls) if self.controls else {}
    
    # def apply_params(self, params_dict):
    #     """Применяет параметры из словаря к элементам UI виджета"""
    #     if not params_dict or not self.ui_elements:
    #         return
        
    #     for param_name, param_value in params_dict.items():
    #         if param_name in self.ui_elements:
    #             element_data = self.ui_elements[param_name]
    #             element = element_data['element']
    #             transfer_k = element_data.get('transfer_k', 1)
                
    #             try:
    #                 from PyQt5.QtWidgets import QSlider
    #                 if isinstance(element, QSlider):
    #                     value = float(param_value)
    #                     value = value / transfer_k
    #                     element.setValue(int(round(value)))
    #             except Exception as e:
    #                 print(f"Ошибка установки значения для {param_name}: {e}")
