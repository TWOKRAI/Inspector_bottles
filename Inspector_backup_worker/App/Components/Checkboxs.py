from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QWidget, QLabel, QCheckBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
import os


class CheckboxControl(QWidget):
    def __init__(self, name, init_val, position="right", min_access = 0, ui_elements=None, controls=[], callback=[], parent=None):
        super().__init__(parent)
        self.name = name
        self.ui_elements = ui_elements
        # self.controls = controls

        # if callback is not None:
        #     self.func_update = callback
        # else:
        #     self.func_update = lambda: None

        # Инициализация списка контролов
        self.controls = controls

        # Инициализация списка функций
        self.func_update = callback

        self.min_access = min_access 

        # Создание компоновки
        self.vbox = QVBoxLayout(self)
        self.vbox.setAlignment(Qt.AlignCenter)

        # Создание виджетов
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(init_val)

        self.value = init_val

        #self.checkbox.setStyleSheet("QCheckBox::indicator { width: 44px; height: 44px; }")
        # Пример с абсолютным путем (адаптируйте под вашу систему)

        unchecked_image_path = r"App/Image/icons8-toggle-off-80.png"
        checked_image_path = r"App/Image/icons8-toggle-on-802.png"

        style = f"""
        QCheckBox::indicator {{
            width: 55px;
            height: 55px;
        }}
        QCheckBox::indicator:unchecked {{
            image: url({unchecked_image_path}) !important;
        }}
        QCheckBox::indicator:checked {{
            image: url({checked_image_path}) !important;
        }}
        """

        self.checkbox.setStyleSheet(style)

        self.checkbox.stateChanged.connect(self.update_control)

        self.label = QLabel(name)
        self.label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(10)
        self.label.setFont(font)

        # Настройка расположения
        self.setup_layout(position)

        if self.ui_elements is not None:
            self.ui_elements[name] = {'element': self.checkbox, 
                                      'value': init_val, 
                                      'min_access': self.min_access}

        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = init_val
            else:
                self.controls[self.name] = init_val


    def setup_layout(self, position):
        if position in ["top", "bottom"]:
            hbox_0 = QHBoxLayout()
            hbox_0.setAlignment(Qt.AlignCenter)
            hbox_1 = QHBoxLayout()
            hbox_1.setAlignment(Qt.AlignCenter)

            if position == "top":
                hbox_0.addStretch()
                hbox_0.addWidget(self.label)
                hbox_0.addStretch()

                hbox_1.addStretch()
                hbox_1.addWidget(self.checkbox)
                hbox_1.addStretch()

                self.vbox.addLayout(hbox_0)
                self.vbox.addLayout(hbox_1)
            else:
                self.vbox.addWidget(self.checkbox)
                self.vbox.addWidget(self.label)
        else:
            hbox = QHBoxLayout()
            hbox.setAlignment(Qt.AlignCenter)
            if position == "left":
                hbox.addWidget(self.label)
                hbox.addWidget(self.checkbox)
            else:
                hbox.addWidget(self.checkbox)
                hbox.addWidget(self.label)
            self.vbox.addLayout(hbox)

    def update_control(self, state):
        self.value = state

        if self.ui_elements is not None:
            self.ui_elements[self.name]['value'] = bool(state)
            
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = bool(state)
            else:
                self.controls[self.name] = bool(state)

        if self.func_update is not None:
            if isinstance(self.controls, list):
                for func_update in self.func_update:
                    func_update()
            else:
                self.func_update()


        print(f"Checkbox {self.name} state changed to {bool(state)}")
