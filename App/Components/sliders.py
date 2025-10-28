from PyQt5.QtWidgets import ( QHBoxLayout, QWidget, QLabel, QSlider)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class SliderControl(QWidget):
    def __init__(self, name, min_val, max_val, init_val, transfer_k=1, round_k=0, min_access = 0, ui_elements=None, controls=[], callback=[], parent=None):
        super().__init__(parent)
        self.name = name
        self.min_access = min_access
        self.ui_elements = ui_elements
        self.controls = controls

        # self.func_update = callbacks if callbacks else lambda: None

        # Инициализация списка контролов
        self.controls = controls

        # Инициализация списка функций
        self.func_update = callback

        self.min_access = min_access 
        
        # Создание компоновки
        self.hbox = QHBoxLayout(self)

        # Создание виджетов
        self.label = QLabel()
        self.value_label = QLabel()
        self.slider = QSlider(Qt.Horizontal)

        # Настройка слайдера
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setValue(init_val)
        self.slider.setMinimumHeight(45)
        self.slider.setMinimumWidth(630)

        self.slider.setStyleSheet("""
            QSlider::handle:horizontal {
                height: 50px;  /* Увеличение высоты в 2 раза */
                width: 25px;   /* Увеличение ширины в 1.5 раза */
                margin: -15px 0;  /* Корректировка отступов для центрирования */
                border: 2px solid #4682B4;
                border-radius: 7px;
                background: gray;
            }
        """)

        self.transfer_k = transfer_k
        self.round_k = round_k

        self.value = self.transfer_value(init_val)

        self.value_label.setText(str(self.value))

        font_family = "Arial"
        font_size = 11
        self.font = QFont(font_family, font_size)
        self.label.setFont(self.font)
        self.label.setWordWrap(True)
        self.label.setFixedSize(100, 40)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setText(name)

        font_family = "Arial"
        font_size = 12
        self.font = QFont(font_family, font_size)
        self.value_label.setFont(self.font)

        # Подключение сигнала изменения значения
        self.slider.valueChanged.connect(self.update_slider_value)
        self.slider.sliderReleased.connect(self.slider_release)

        # Отключение прокрутки колесом мыши
        self.slider.wheelEvent = lambda event: None

        # Добавление виджетов в компоновку
        self.hbox.addSpacing(25)
        self.hbox.addWidget(self.label)
        self.hbox.addStretch()
        self.hbox.addWidget(self.value_label)
        self.hbox.addSpacing(10)
        self.hbox.addWidget(self.slider)
        self.hbox.addSpacing(25)

        if self.ui_elements is not None:
            self.ui_elements[name] = {'element': self.slider, 'value': init_val, 'min_access': self.min_access}

        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value
            else:
                self.controls[self.name] = self.value


    def update_slider_value(self, value):
        self.value = value
        self.value_transfer = self.transfer_value(self.value)

        self.value_label.setText(str(self.value_transfer))

        if self.ui_elements is not None:
            self.ui_elements[self.name]['value'] = self.value_transfer
        
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value_transfer
            else:
                self.controls[self.name] = self.value_transfer

        if self.func_update is not None:
            if isinstance(self.controls, list):
                for func_update in self.func_update:
                    func_update()
            else:
                self.func_update()

        
    def slider_release(self):
        print(f"Slider {self.name} value changed to {self.value}")


    def transfer_value(self, value):
        value_k = value * self.visual_k

        if self.round_k == 0:
            print(int(round(value_k, self.round_k)))
            return int(round(value_k, self.round_k)) 
        else:
            print(round(value_k, self.round_k))
            return round(value_k, self.round_k)
        

    def transfer_value(self, value):
        value_k = value * self.transfer_k
        rounded = round(value_k, self.round_k)
        return int(rounded) if self.round_k == 0 else rounded


from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QLabel, QSlider
from PyQt5.QtGui import QFont, QIntValidator, QDoubleValidator
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QTimer

from App.Components.keyboard_mini import VirtualKeyboardMini


class SliderControl_change(QWidget):
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

        # Настройка шрифтов
        font = QFont("Arial", 11)

        self.label = QLabel()
        self.label.setText(label) 
        self.label.setFont(font)
        self.label.setWordWrap(True)
        self.label.setFixedSize(145, 40)
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
        self.slider.setMinimumWidth(630)

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
        self.hbox.addSpacing(5)
        self.hbox.addWidget(self.label)
        self.hbox.addStretch()
        self.hbox.addWidget(self.value_input)
        self.hbox.addSpacing(20)
        self.hbox.addWidget(self.slider)
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
        return round(value_k, self.round_k) if self.round_k != 0 else int(value_k)


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

