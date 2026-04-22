# -*- coding: utf-8 -*-
"""
VirtualKeyboardMini — компактная цифровая клавиатура (touch-ввод).
"""
from __future__ import annotations

from frontend_module.core.qt_imports import QFont, QGridLayout, QPushButton, QVBoxLayout, QWidget, Qt
from frontend_module.widgets.widget_signal_bus import WidgetSignalBus


class VirtualKeyboardMini(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._signal_bus = WidgetSignalBus(parent=self)
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
        self.apply_geometry_for_touch()

    def apply_geometry_for_touch(
        self,
        width_px: int = 300,
        height_px: int = 250,
        scale: float = 1.0,
    ) -> None:
        w = max(80, int(width_px * scale))
        h = max(80, int(height_px * scale))
        self.resize(w, h)

    @property
    def signal_bus(self) -> WidgetSignalBus:
        return self._signal_bus

    def emit_widget_event(self, event_id: str, payload: object = None) -> None:
        self._signal_bus.event_emitted.emit(event_id, payload)

    def closeEvent(self, event):
        self.emit_widget_event("keyboard.mini.closed", None)
        super().closeEvent(event)

    def on_button_clicked(self, text):
        if self.input is None:
            return
        if text == 'Backspace':
            current = self.input.text()
            self.input.setText(current[:-1])
        elif text == 'Clear':
            self.input.setText('')
        elif text == 'Enter':
            self.emit_widget_event("keyboard.mini.enter", None)
            if self.enter:
                self.enter()
            self.close()
        else:
            current = self.input.text()
            self.input.setText(current + text)
