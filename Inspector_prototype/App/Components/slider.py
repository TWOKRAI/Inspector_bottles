from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QLabel, QSlider
from PyQt5.QtGui import QFont, QIntValidator, QDoubleValidator
from PyQt5.QtCore import Qt, QSize, pyqtSignal

from App.Components.keyboard import VirtualKeyboard


class SliderControl2(QWidget):
    def __init__(self, name, min_val, max_val, init_val, transfer_k=1, round_k=0, min_access=0, ui_elements=None, controls=[], callback=[], parent=None, label="slider_1"):
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

        # Создание виджетов
        self.label = QLabel()
        self.label.setText(label)  # Установка переданного или дефолтного label
        self.value_input = QLineEdit()
        self.slider = QSlider(Qt.Horizontal)

        # Настройка слайдера
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setValue(init_val)
        self.slider.setMinimumHeight(45)
        self.slider.setMinimumWidth(690)

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

        # Инициализация значения
        self.value = self.transfer_value(init_val)
        self.value_input.setText(str(self.value))

        # Настройка шрифтов
        font = QFont("Arial", 11)
        self.label.setFont(font)
        self.label.setWordWrap(True)
        self.label.setFixedSize(100, 40)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Валидатор для поля ввода
        if self.round_k == 0:
            validator = QIntValidator()
        else:
            validator = QDoubleValidator()
            
        self.value_input.setValidator(validator)

        # Подключение сигналов
        self.slider.valueChanged.connect(self.update_slider_value)
        self.value_input.editingFinished.connect(self.update_input_value)
        self.value_input.mousePressEvent = self.show_touch_keyboard

        # Отключение прокрутки колесом мыши
        self.slider.wheelEvent = lambda event: None

        # Добавление виджетов в компоновку
        self.hbox.addSpacing(25)
        self.hbox.addWidget(self.label)
        self.hbox.addStretch()
        self.hbox.addWidget(self.value_input)
        self.hbox.addSpacing(10)
        self.hbox.addWidget(self.slider)
        self.hbox.addSpacing(25)

        # Обновление внешних элементов
        if self.ui_elements is not None:
            self.ui_elements[name] = {'element': self.slider, 'value': self.value, 'min_access': self.min_access}

        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value
            else:
                self.controls[self.name] = self.value

    def update_slider_value(self, value):
        # Обновление значения из слайдера
        self.value = self.transfer_value(value)
        self.value_input.setText(str(self.value))
        self.update_external()

    def update_input_value(self):
        # Обновление значения из поля ввода
        try:
            input_value = float(self.value_input.text())
            slider_value = int(round(input_value / self.transfer_k))
            slider_value = max(self.slider.minimum(), min(slider_value, self.slider.maximum()))
            self.slider.setValue(slider_value)
            self.value = self.transfer_value(slider_value)
            self.update_external()
        except ValueError:
            self.value_input.setText(str(self.value))

    def update_external(self):
        # Обновление внешних элементов управления
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
        return round(value_k, self.round_k) if self.round_k != 0 else int(value_k)

    def show_touch_keyboard(self, event):
        # Показ кастомной клавиатуры
        self.keyboard = VirtualKeyboard()
        self.keyboard.input = self.value_input
        self.keyboard.enter = self.update_input_value
        self.keyboard.show()
        self.keyboard.raise_()
        self.keyboard.activateWindow()
        super(QLineEdit, self.value_input).mousePressEvent(event)

    def slider_release(self):
        print(f"Slider {self.name} value changed to {self.value}")