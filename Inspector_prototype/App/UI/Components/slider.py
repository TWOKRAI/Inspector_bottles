from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QLabel, QSlider
from PyQt5.QtGui import QFont, QIntValidator, QDoubleValidator
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QTimer

from App.Components.keyboard_mini import VirtualKeyboardMini


class SliderControl(QWidget):
    def __init__(self, name, min_val, max_val, init_val, transfer_k=1, round_k=0, min_access=0, ui_elements=None, controls=[], callback=[], parent=None, label=None):
        super().__init__(parent)
        self.name = name
        self.min_access = min_access
        self.ui_elements = ui_elements
        self.controls = controls
        self.func_update = callback
        self.transfer_k = transfer_k
        self.round_k = round_k

        # Инициализация компоновки
        self.hbox = QHBoxLayout(self)

        # Настройка шрифтов
        font = QFont("Arial", 11)

        self.label = QLabel()
        # Используем name как label, если label не указан
        display_label = label if label is not None else name
        self.label.setText(display_label) 
        self.label.setFont(font)
        self.label.setWordWrap(True)
        # Имя занимает 30% ширины, поэтому не фиксируем размер, а используем stretch factor
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.value = self.transfer_value(init_val)

        self.value_input = QLineEdit()
        font.setPointSize(12)
        self.value_input.setFont(font)
        self.value_input.setFixedSize(60, 30)
        self.value_input.setAlignment(Qt.AlignCenter)

        self.value_input.setText(str(self.value))

        # Валидатор для поля ввода
        if self.round_k == 0:
            validator = QIntValidator()
        else:
            validator = QDoubleValidator()
            validator.setNotation(QDoubleValidator.StandardNotation)

        self.value_input.setValidator(validator)

        self.slider = QSlider(Qt.Horizontal)

        # Настройка слайдера
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setValue(init_val)
        self.slider.setMinimumHeight(45)
        # Убрана фиксированная ширина, чтобы слайдер мог растягиваться согласно пропорциям

        self.slider.setStyleSheet("""
            QSlider::handle:horizontal {
                height: 50px;
                width: 25px;
                margin: -15px 0;
                border: 2px solid #4682B4;
                border-radius: 7px;
                background: gray;
            }
        """)

        # Подключение сигналов
        self.slider.valueChanged.connect(self.update_slider_value)
        self.value_input.editingFinished.connect(self.update_input_value)
        self.value_input.mousePressEvent = self.show_touch_keyboard

        # Отключение прокрутки колесом мыши
        self.slider.wheelEvent = lambda event: None

        # Добавление виджетов в компоновку
        # Имя занимает 15% ширины, регуляторы - 85%
        self.hbox.addSpacing(5)
        self.hbox.addWidget(self.label, 3)  # 15% ширины (stretch factor 3 из 20)
        self.hbox.addWidget(self.value_input)
        self.hbox.addSpacing(20)
        self.hbox.addWidget(self.slider, 17)  # 85% ширины (stretch factor 17 из 20)
        self.hbox.addSpacing(25)

        # Обновление внешних элементов
        if self.ui_elements is not None:
            self.ui_elements[name] = {'element': self.slider, 
                                        'value': self.value, 
                                        'min_access': self.min_access,
                                        'transfer_k': transfer_k,
                                        'round_k': round_k}

        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value
            else:
                self.controls[self.name] = self.value

        self.block = False


    def update_slider_value(self, value):
        # Обновление значения из слайдера
        self.value = self.transfer_value(value)
        self.value_input.setText(str(self.value))

        if not self.block:
            self.block = True
            QTimer.singleShot(100, self.onTimeout)


    def update_input_value(self):
        # Обновление значения из поля ввода
        try:
            input_text = self.value_input.text()
            # Заменяем запятую на точку, если нужно
            input_text = input_text.replace(',', '.')
            input_value = float(input_text)
            slider_value = int(round(input_value / self.transfer_k))
            slider_value = max(self.slider.minimum(), min(slider_value, self.slider.maximum()))
            self.slider.setValue(slider_value)
            self.value = self.transfer_value(slider_value)
            
            self.update_external()
        except ValueError:
            self.value_input.setText(str(self.value))
  
  
    def onTimeout(self):
       self.update_external()
       self.block = False
    

    def update_external(self):
        if self.ui_elements is not None:
            self.ui_elements[self.name]['value'] = self.value
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value
            else:
                self.controls[self.name] = self.value
        if self.func_update is not None:
            if isinstance(self.func_update, list):
                for func in self.func_update:
                    func()
            else:
                self.func_update()


    def transfer_value(self, value):
        # Преобразование значения слайдера
        value_k = value * self.transfer_k
        rounded = round(value_k, self.round_k)
        return int(rounded) if self.round_k == 0 else rounded


    def show_touch_keyboard(self, event):
        # Показ кастомной клавиатуры
        self.keyboard = VirtualKeyboardMini()
        self.keyboard.input = self.value_input
        self.keyboard.enter = self.update_input_value
        self.keyboard.show()
        self.keyboard.raise_()
        self.keyboard.activateWindow()
        super(QLineEdit, self.value_input).mousePressEvent(event)


    def slider_release(self):
        self.update_external()
        print(f"Slider {self.name} value changed to {self.value}")

