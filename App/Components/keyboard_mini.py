from PyQt5.QtWidgets import (
    QPushButton, QApplication, QGridLayout, QWidget, QHBoxLayout
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QSize


class VirtualKeyboardMini(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Виртуальная клавиатура мини")
        #self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowFlags(self.windowFlags() & ~Qt.FramelessWindowHint)
        self.showNormal()

        self.setFixedSize(360, 300)

        self.state_show = False
        self.position_index = 0

        self.input = None
        self.enter = None

        self.shift_active = False
        self.language_english = True
        self.symbol_mode = False
        self.buttons = []

        self.button_width = 60
        self.button_height = 50
        self.functional_button_width_left = 80
        self.functional_button_height_left = 50
        self.functional_button_width = 140
        self.functional_button_height = 50

        self.font_name = "Arial"
        self.font_size_letters = 16
        self.font_size_functional = 16

        self.layout = QGridLayout()
        self.layout.setSpacing(5)

        self.buttons_text_numbers = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '-', '0', '.']

        self.setup_ui()


    def setup_ui(self):
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        self.buttons = []
        
        positions = [(i, j) for i in range(1, 5) for j in range(1, 4)]
        for position, button_text in zip(positions, self.buttons_text_numbers):
            btn = QPushButton(button_text)
            btn.setFixedSize(QSize(self.button_width, self.button_height))
            btn.setFont(QFont(self.font_name, self.font_size_letters))
            btn.clicked.connect(self.on_button_clicked)
            self.layout.addWidget(btn, *position)
            self.buttons.append(btn)

        num_columns = 5

        # Создаем контейнер для кнопок Mv и X
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)  # Устанавливаем расстояние между кнопками

        # Кнопка перемещения окна
        move_btn = QPushButton("Move")
        move_btn.setFixedSize(QSize(self.button_width + 20, self.functional_button_height))
        move_btn.setFont(QFont(self.font_name, self.font_size_functional))
        move_btn.clicked.connect(self.change_window_position)
        button_layout.addWidget(move_btn)

        # Кнопка закрытия
        close_btn = QPushButton("X")
        close_btn.setFixedSize(QSize(self.button_width - 5, self.functional_button_height))
        close_btn.setFont(QFont(self.font_name, self.font_size_functional))
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        # Добавляем контейнер в сетку
        self.layout.addWidget(button_container, 1, num_columns, 1, 2)

        backspace_btn = QPushButton("Backspace")
        backspace_btn.setFixedSize(QSize(self.functional_button_width, self.functional_button_height))
        backspace_btn.setFont(QFont(self.font_name, self.font_size_functional))
        backspace_btn.clicked.connect(self.on_backspace_clicked)
        self.layout.addWidget(backspace_btn, 2, num_columns, 1, 2)

        enter_btn = QPushButton("Enter")
        enter_btn.setFixedSize(QSize(self.functional_button_width, self.functional_button_height))
        enter_btn.setFont(QFont(self.font_name, self.font_size_functional))
        enter_btn.clicked.connect(self.on_enter_clicked)
        self.layout.addWidget(enter_btn, 3, num_columns, 1, 2)

        space_btn = QPushButton("Space")
        space_btn.setFixedSize(QSize(self.functional_button_width, self.functional_button_height))
        space_btn.setFont(QFont(self.font_name, self.font_size_functional))
        space_btn.clicked.connect(self.on_space_clicked)
        self.layout.addWidget(space_btn, 4, num_columns, 1, 2)

        self.setLayout(self.layout)
        screen_geometry = QApplication.primaryScreen().geometry()

        self.btn_е = None

        self.apply_states()

    def close(self) -> bool:
        super().close()
        self.input = None
        self.enter = None
        self.state_show = False

    def show(self):
        super().show()
        self.activateWindow()  
        self.raise_()


    def toggle_float(self):
        if self.windowFlags() & Qt.FramelessWindowHint:
            self.setWindowFlags(self.windowFlags() & ~Qt.FramelessWindowHint)
            self.showNormal()
        else:
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self.show()
            screen_geometry = QApplication.primaryScreen().geometry()
            self.setGeometry(0, screen_geometry.height() - screen_geometry.height() // 3, screen_geometry.width(), screen_geometry.height() // 3)


    def on_button_clicked(self):
        button = self.sender()

        if self.input is not None:
            self.input.insert(button.text())


    def on_backspace_clicked(self):
        if self.input is not None:
            self.input.backspace()


    def on_space_clicked(self):
        if self.input is not None:
            self.input.insert(" ")


    def on_enter_clicked(self):
        if self.enter is not None:
            self.enter()


    def on_shift_clicked(self):
        self.shift_active = not self.shift_active
        current_buttons_text = self.buttons_text_english if self.language_english else self.buttons_text_russian
        for btn, text in zip(self.buttons[10:], current_buttons_text):
            new_text = text.upper() if self.shift_active else text.lower()
            btn.setText(new_text)

        self.shift_btn.setText("shift" if self.shift_active else "SHIFT")

        if self.btn_е:
            new_text = 'Ё' if self.shift_active else 'ё'
            self.btn_е.setText(new_text)


    def on_language_clicked(self):
        self.language_english = not self.language_english
        self.setup_ui()

        if not self.language_english:
            self.btn_е = QPushButton('Ё' if self.shift_active else 'ё')
            self.btn_е.setFixedSize(QSize(self.button_width, self.button_height))
            self.btn_е.setFont(QFont(self.font_name, self.font_size_letters))
            self.btn_е.clicked.connect(self.on_button_clicked)
            self.layout.addWidget(self.btn_е, 0, 11, 1, 1)


    def on_symbol_clicked(self):
        self.symbol_mode = not self.symbol_mode
        current_buttons_text = self.buttons_text_symbols if self.symbol_mode else self.buttons_text_numbers
        for btn, text in zip(self.buttons[:10], current_buttons_text):
            btn.setText(text)
        self.symbol_btn.setText("123" if self.symbol_mode else "!@#")


    def apply_states(self):
        if self.shift_active:
            current_buttons_text = self.buttons_text_english if self.language_english else self.buttons_text_russian
            for btn, text in zip(self.buttons[10:], current_buttons_text):
                btn.setText(text.upper())
            self.shift_btn.setText("shift")
            if self.btn_е:
                self.btn_е.setText('Ё')

        if self.symbol_mode:
            current_buttons_text = self.buttons_text_symbols
            for btn, text in zip(self.buttons[:10], current_buttons_text):
                btn.setText(text)
            self.symbol_btn.setText("123")


    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Shift:
            self.on_shift_clicked()
    

    def change_window_position(self):
        """Изменяет позицию окна по циклу из 4 позиций"""
        self.position_index = (self.position_index + 1) % 4
        self.update_position()


    def update_position(self):
        """Обновляет позицию окна в соответствии с текущим position_index"""
        screen_geometry = QApplication.primaryScreen().geometry()
        window_width = self.width()
        window_height = self.height()
        
        if self.position_index == 0:  # Верхний левый угол
            self.move(0, 0)
        elif self.position_index == 1:  # Верхний правый угол
            self.move(screen_geometry.width() - window_width, 0)
        elif self.position_index == 2:  # Нижний правый угол
            self.move(screen_geometry.width() - window_width, 
                screen_geometry.height() - window_height - 50)       
        elif self.position_index == 3:  # Нижний левый угол
            self.move(0, screen_geometry.height() - window_height - 50)


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    keyboard = VirtualKeyboardMini()
    keyboard.show()
    sys.exit(app.exec_())