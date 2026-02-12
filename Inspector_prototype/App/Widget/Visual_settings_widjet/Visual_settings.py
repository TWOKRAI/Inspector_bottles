from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
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
