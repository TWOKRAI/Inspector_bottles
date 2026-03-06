from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class CheckboxControl(QWidget):
    def __init__(self, name, init_val, position="right", min_access=0, ui_elements=None, controls=[], callback=[], parent=None):
        super().__init__(parent)
        self.name = name
        self.ui_elements = ui_elements
        self.controls = controls
        self.func_update = callback
        self.min_access = min_access 

        # Создание компоновки
        self.vbox = QVBoxLayout(self)
        self.vbox.setAlignment(Qt.AlignCenter)

        # Создание виджетов
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(init_val)
        self.checkbox.setStyleSheet("QCheckBox::indicator { width: 44px; height: 44px; }")
        self.checkbox.stateChanged.connect(self.update_control)

        self.label = QLabel(name)
        self.label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
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
        if self.ui_elements is not None:
            self.ui_elements[self.name]['value'] = bool(state)
            
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = bool(state)
            else:
                self.controls[self.name] = bool(state)

        if self.func_update is not None:
            if isinstance(self.func_update, list):
                for func_update in self.func_update:
                    func_update()
            else:
                self.func_update()

        print(f"Checkbox {self.name} state changed to {bool(state)}")
