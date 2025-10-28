from PyQt5.QtWidgets import (
    QPushButton, QApplication, QGridLayout, QWidget
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QSize

class VirtualKeyboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Виртуальная клавиатура")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.state_show = False

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

        self.buttons_text_english = [
            'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p',
            'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', '?',
            'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '!'
        ]

        self.buttons_text_russian = [
            'й', 'ц', 'у', 'к', 'е', 'н', 'г', 'ш', 'щ', 'з', 'х', 'ъ',
            'ф', 'ы', 'в', 'а', 'п', 'р', 'о', 'л', 'д', 'ж', 'э', '?',
            'я', 'ч', 'с', 'м', 'и', 'т', 'ь', 'б', 'ю', ',', '.', '!'
        ]

        self.buttons_text_numbers = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
        self.buttons_text_symbols = ['+', '-', '*', '/', '=', '@', '#', '%', '(', ')']

        self.setup_ui()

    def setup_ui(self):
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        self.buttons = []

        num_columns = 11 if self.language_english else 13
        positions = [(0, j) for j in range(1, num_columns)]
        for position, button_text in zip(positions, self.buttons_text_numbers):
            btn = QPushButton(button_text)
            btn.setFixedSize(QSize(self.button_width, self.button_height))
            btn.setFont(QFont(self.font_name, self.font_size_letters))
            btn.clicked.connect(self.on_button_clicked)
            self.layout.addWidget(btn, *position)
            self.buttons.append(btn)

        current_buttons_text = self.buttons_text_english if self.language_english else self.buttons_text_russian
        positions = [(i, j) for i in range(1, 4) for j in range(1, num_columns)]
        for position, button_text in zip(positions, current_buttons_text):
            btn = QPushButton(button_text)
            btn.setFixedSize(QSize(self.button_width, self.button_height))
            btn.setFont(QFont(self.font_name, self.font_size_letters))
            btn.clicked.connect(self.on_button_clicked)
            self.layout.addWidget(btn, *position)
            self.buttons.append(btn)

        self.symbol_btn = QPushButton("!@#" if not self.symbol_mode else "123")
        self.symbol_btn.setFixedSize(QSize(self.functional_button_width_left, self.functional_button_height_left))
        self.symbol_btn.setFont(QFont(self.font_name, self.font_size_functional))
        self.symbol_btn.clicked.connect(self.on_symbol_clicked)
        self.layout.addWidget(self.symbol_btn, 0, 0, 1, 1)

        self.language_btn = QPushButton("ru" if self.language_english else "en")
        self.language_btn.setFixedSize(QSize(self.functional_button_width_left, self.functional_button_height_left))
        self.language_btn.setFont(QFont(self.font_name, self.font_size_functional))
        self.language_btn.clicked.connect(self.on_language_clicked)
        self.layout.addWidget(self.language_btn, 1, 0, 1, 1)

        self.shift_btn = QPushButton("SHIFT" if not self.shift_active else "shift")
        self.shift_btn.setFixedSize(QSize(self.functional_button_width_left, self.functional_button_height_left))
        self.shift_btn.setFont(QFont(self.font_name, self.font_size_functional))
        self.shift_btn.clicked.connect(self.on_shift_clicked)
        self.layout.addWidget(self.shift_btn, 2, 0, 1, 1)

        float_btn = QPushButton("O")
        float_btn.setFixedSize(QSize(self.button_width - 5, self.functional_button_height))
        float_btn.setFont(QFont(self.font_name, self.font_size_functional))
        float_btn.clicked.connect(self.toggle_float)
        self.layout.addWidget(float_btn, 0, num_columns, 1, 1)

        close_btn = QPushButton("X")
        close_btn.setFixedSize(QSize(self.button_width - 5, self.functional_button_height))
        close_btn.setFont(QFont(self.font_name, self.font_size_functional))
        close_btn.clicked.connect(self.close)
        self.layout.addWidget(close_btn, 0, num_columns + 1, 1, 1)


        backspace_btn = QPushButton("Backspace")
        backspace_btn.setFixedSize(QSize(self.functional_button_width, self.functional_button_height))
        backspace_btn.setFont(QFont(self.font_name, self.font_size_functional))
        backspace_btn.clicked.connect(self.on_backspace_clicked)
        self.layout.addWidget(backspace_btn, 1, num_columns, 1, 2)

        enter_btn = QPushButton("Enter")
        enter_btn.setFixedSize(QSize(self.functional_button_width, self.functional_button_height))
        enter_btn.setFont(QFont(self.font_name, self.font_size_functional))
        enter_btn.clicked.connect(self.on_enter_clicked)
        self.layout.addWidget(enter_btn, 2, num_columns, 1, 2)

        space_btn = QPushButton("Space")
        space_btn.setFixedSize(QSize(self.functional_button_width, self.functional_button_height))
        space_btn.setFont(QFont(self.font_name, self.font_size_functional))
        space_btn.clicked.connect(self.on_space_clicked)
        self.layout.addWidget(space_btn, 3, num_columns, 1, 2)

        self.setLayout(self.layout)
        screen_geometry = QApplication.primaryScreen().geometry()
        self.setGeometry(0, screen_geometry.height() - screen_geometry.height() // 3, screen_geometry.width(), screen_geometry.height() // 3)

        self.btn_е = None

        self.apply_states()

    def close(self) -> bool:
        super().close()
        self.input = None
        self.enter = None
        self.state_show = False

    def show(self):
        # if not self.state_show:
        #     super().show()
        #     self.state_show = True

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

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    keyboard = VirtualKeyboard()
    keyboard.show()
    sys.exit(app.exec_())