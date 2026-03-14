import sys
from typing import Dict, Tuple, Any

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, \
                             QWidget, QTextEdit, QLineEdit, QPushButton, QLabel, \
                             QCheckBox, QGroupBox
from PySide6.QtCore import QObject, Signal, Qt

from .gui_process_module import GUIProcessModule
from .window_manager import BaseWindowManager, WindowConfig


class ChatSignals(QObject):
    """Сигналы для PyQt GUI чата"""
    message_received = Signal(str, str)
    status_updated = Signal(str)


class ChatWindow(QMainWindow):
    """Окно чата на PyQt"""
    
    def __init__(self, window_manager):
        super().__init__()
        self.window_manager = window_manager
        self.process_name = window_manager.process_module.name
        self.chat_signals = ChatSignals()
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка интерфейса чата"""
        self.setWindowTitle(f"Chat - {self.process_name}")
        self.setGeometry(100, 100, 500, 400)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Группа выбора получателей
        targets_group = QGroupBox("Send to:")
        targets_layout = QVBoxLayout(targets_group)
        
        self.target_checkboxes = {}
        available_targets = ["Bob", "Alice", "Mike"]  # Заглушка
        
        for target in available_targets:
            cb = QCheckBox(target)
            cb.setChecked(True)
            self.target_checkboxes[target] = cb
            targets_layout.addWidget(cb)
        
        # Кнопка "Broadcast to All"
        self.broadcast_checkbox = QCheckBox("Broadcast to All")
        targets_layout.addWidget(self.broadcast_checkbox)
        
        layout.addWidget(targets_group)
        
        # Отображение чата
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        layout.addWidget(self.chat_display)
        
        # Статусная строка
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        
        # Панель ввода
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type your message...")
        self.send_button = QPushButton("Send")
        
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)
        
        # Подключение сигналов
        self.send_button.clicked.connect(self.send_message)
        self.message_input.returnPressed.connect(self.send_message)
        
        self.add_system_message(f"Chat started as {self.process_name}")
        
    def get_selected_targets(self):
        """Получение выбранных получателей"""
        return [name for name, cb in self.target_checkboxes.items() if cb.isChecked()]
        
    def send_message(self):
        """Отправка сообщения"""
        text = self.message_input.text().strip()
        if not text:
            return
            
        # Отправка через процесс менеджер
        if self.broadcast_checkbox.isChecked():
            # Broadcast сообщение
            self.window_manager.process_module.send_gui_message(
                "chat_broadcast", 
                text
            )
            self.add_system_message(f"[BROADCAST] {text}")
        else:
            # Отправка конкретным получателям
            targets = self.get_selected_targets()
            self.window_manager.process_module.send_gui_message(
                "chat_message", 
                {"message": text},
                targets=targets
            )
            self.add_system_message(f"To {', '.join(targets)}: {text}")
        
        self.message_input.clear()
        
    def add_system_message(self, message: str):
        """Добавление системного сообщения"""
        self.chat_display.append(f"<b>System:</b> {message}")
    
    def display_message(self, sender: str, message: str):
        """Отображение входящего сообщения"""
        self.chat_display.append(f"<b>{sender}:</b> {message}")


class ChatGUIProcess(GUIProcessModule):
    """GUI процесс для чат-приложения"""
    
    def get_window_configs(self) -> Dict[str, WindowConfig]:
        """Конфигурация окон чата"""
        return {
            'chat': WindowConfig(
                name='chat',
                window_class=ChatWindow,
                show_on_start=True,
                fullscreen=False
            )
        }
    
    def create_gui_application(self) -> Tuple[Any, BaseWindowManager]:
        """Создание приложения чата"""
        app = QApplication(sys.argv)
        
        window_configs = self.get_window_configs()
        window_manager = BaseWindowManager(self, app, window_configs)
        window_manager.initialize_windows()
        
        return app, window_manager
