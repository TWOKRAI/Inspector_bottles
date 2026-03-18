# -*- coding: utf-8 -*-
"""
VirtualKeyboardMini — компактная цифровая клавиатура (touch-ввод).
"""
from __future__ import annotations

try:
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QGridLayout
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont
    _HAS_QT = True
except ImportError:
    _HAS_QT = False


if _HAS_QT:

    class VirtualKeyboardMini(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.input = None
            self.enter = None
            self.init_ui()

        def init_ui(self):
            self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
            self.setStyleSheet("""
                QPushButton {
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 5px;
                    padding: 10px;
                    font-size: 16px;
                    min-width: 50px;
                    min-height: 50px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
            """)
            layout = QVBoxLayout(self)
            grid = QGridLayout()
            buttons = [
                ['7', '8', '9', '/'],
                ['4', '5', '6', '*'],
                ['1', '2', '3', '-'],
                ['0', '.', ',', '+'],
                ['Backspace', 'Clear', 'Enter', '']
            ]
            for row, button_row in enumerate(buttons):
                for col, text in enumerate(button_row):
                    if text:
                        btn = QPushButton(text)
                        btn.clicked.connect(lambda checked, t=text: self.on_button_clicked(t))
                        grid.addWidget(btn, row, col)
            layout.addLayout(grid)
            self.setLayout(layout)
            self.resize(300, 250)

        def on_button_clicked(self, text):
            if self.input is None:
                return
            if text == 'Backspace':
                current = self.input.text()
                self.input.setText(current[:-1])
            elif text == 'Clear':
                self.input.setText('')
            elif text == 'Enter':
                if self.enter:
                    self.enter()
                self.close()
            else:
                current = self.input.text()
                self.input.setText(current + text)

else:
    VirtualKeyboardMini = None  # type: ignore
