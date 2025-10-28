from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QIntValidator
from PyQt5.QtCore import Qt, pyqtSignal  
from PyQt5.QtWidgets import QMessageBox

class SpinWidget(QtWidgets.QWidget):
    applied = pyqtSignal(int)    
    saved = pyqtSignal(int)    
    default = pyqtSignal(int)    
    
    def __init__(self, number_value):
        super().__init__()
        
        self.min_value = 0
        self.max_value = 21
        # Загружаем значение из файла при инициализации
        self.number_value = self.load_value(number_value)
        
        self.btn_left = QtWidgets.QPushButton("←")
        self.input = QtWidgets.QLineEdit()
        self.btn_right = QtWidgets.QPushButton("→")
        self.apply_btn = QtWidgets.QPushButton("Загрузить")
        self.save_btn = QtWidgets.QPushButton("Сохранить")
        self.default_btn = QtWidgets.QPushButton("По дефолту")
        
        self.input.setAlignment(Qt.AlignCenter)
        self.input.setFixedWidth(60)
        self.input.setText(str(self.number_value))
        self.input.setValidator(QIntValidator(self.min_value, self.max_value))
        
        self._setup_sizes()
        
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.addStretch()
        self.layout.addWidget(self.btn_left)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.input)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.btn_right)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.apply_btn)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.save_btn)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.default_btn)
        self.layout.addStretch()
        
        self.btn_left.clicked.connect(self.decrement)
        self.btn_right.clicked.connect(self.increment)
        self.input.textChanged.connect(self.validate_input)
        self.apply_btn.clicked.connect(self._emit_applied)   
        self.save_btn.clicked.connect(self._emit_saved)
        self.default_btn.clicked.connect(self._emit_default)
        
        # Связываем сигнал сохранения с методом записи в файл
        self.saved.connect(self.save_value)
        
        self.update_buttons()

    def _setup_sizes(self):
        """Настройка размеров элементов"""
        self.btn_left.setFixedSize(60, 50)
        self.btn_right.setFixedSize(60, 50)
        self.input.setFixedSize(70, 50)
        button_size = QtCore.QSize(100, 50)
        self.apply_btn.setFixedSize(button_size)
        self.save_btn.setFixedSize(button_size)
        self.default_btn.setFixedSize(button_size)

    def _show_confirmation_dialog(self, title, message):
        dialog = QMessageBox(
            QMessageBox.Question,
            title,
            f"<center>{message}</center>",
            QMessageBox.Yes | QMessageBox.No,
            parent=self
        )
        dialog.setTextFormat(QtCore.Qt.RichText)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec_() == QMessageBox.Yes

    def _emit_applied(self):
        if self._show_confirmation_dialog(
            "Подтверждение применения",
            f"Вы уверены, что хотите применить значения в сорт-{self.number_value}?"
        ):
            self.applied.emit(self.number_value)

    def _emit_saved(self):
        if self._show_confirmation_dialog(
            "Подтверждение сохранения",
            f"Вы уверены, что хотите сохранить значения в сорт-{self.number_value}?"
        ):
            self.saved.emit(self.number_value)
    
    def _emit_default(self):
        if self._show_confirmation_dialog(
            "Подтверждение сохранения",
            f"Вы уверены, что хотите сделать значения сорта-{self.number_value} по дефолту?"
        ):
            self.default.emit(self.number_value)

    def validate_input(self):
        try:
            new_value = int(self.input.text())
        except ValueError:
            new_value = self.min_value
            
        self.number_value = max(self.min_value, min(self.max_value, new_value))
        self.input.setText(str(self.number_value))
        self.update_buttons()

    def get_value(self):
        return self.number_value

    def set_value(self, value):
        self.number_value = max(self.min_value, min(self.max_value, value))
        self.input.setText(str(self.number_value))
        self.update_buttons()

        self.save_value(self.number_value)

    def update_buttons(self):
        self.btn_left.setEnabled(self.number_value > self.min_value)
        self.btn_right.setEnabled(self.number_value < self.max_value)

    def decrement(self):
        self.set_value(self.number_value - 1)

    def increment(self):
        self.set_value(self.number_value + 1)

    def save_value(self, value):
        """Сохраняет текущее значение в файл"""
        with open("value.dat", "w") as file:
            file.write(str(value))

    def load_value(self, default_value):
        """
        Загружает значение из файла. 
        Если файла нет или данные повреждены - использует default_value
        """
        try:
            with open("value.dat", "r") as file:
                value = int(file.read())
                print(value, type(value ))
                # Проверка на допустимый диапазон
                if self.min_value <= value <= self.max_value:
                    return value
                raise ValueError
        except (FileNotFoundError, ValueError):
            self.save_value(default_value)
            return default_value

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    widget = SpinWidget(2)  # Значение по умолчанию 2, если файла нет
    widget.resize(400, 50)
    widget.show()
    sys.exit(app.exec_())