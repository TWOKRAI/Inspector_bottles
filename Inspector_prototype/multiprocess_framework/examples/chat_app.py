
import sys
import time
from typing import List, Dict
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
    QWidget, QTextEdit, QLineEdit, QPushButton, QLabel, 
    QCheckBox, QGroupBox
)
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QTextCursor

from multiprocess_framework.Process_module.process_module import ProcessModule
from multiprocess_framework.Process_manager_module.Processes_Manager import ProcessManager
from multiprocess_framework.Message_module.message import Message
from multiprocess_framework.Message_module.message_types import MessageType


class ChatSignals(QObject):
    """Сигналы для PySide6 GUI"""
    message_received = Signal(str, str)  # sender, text


class ChatWindow(QMainWindow):
    """Простое окно чата на PySide6"""
    
    def __init__(self, chat_process, process_name: str):
        super().__init__()
        self.chat_process = chat_process
        self.process_name = process_name
        self.setup_ui()
        
        # Таймер для обновления списка получателей
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_targets)
        self.update_timer.start(2000)  # Обновление каждые 2 секунды
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle(f"Chat - {self.process_name}")
        self.setGeometry(100, 100, 600, 500)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Группа выбора получателей
        targets_group = QGroupBox("Отправить:")
        targets_layout = QVBoxLayout(targets_group)
        
        self.target_checkboxes = {}
        self._update_targets()  # Первоначальное обновление
        
        # Кнопка "Broadcast to All"
        self.broadcast_checkbox = QCheckBox("Отправить всем (Broadcast)")
        targets_layout.addWidget(self.broadcast_checkbox)
        
        layout.addWidget(targets_group)
        
        # Отображение чата
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        layout.addWidget(self.chat_display)
        
        # Статусная строка
        self.status_label = QLabel("Готов")
        layout.addWidget(self.status_label)
        
        # Панель ввода
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Введите сообщение...")
        self.send_button = QPushButton("Отправить")
        
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)
        
        # Подключение сигналов
        self.send_button.clicked.connect(self.send_message)
        self.message_input.returnPressed.connect(self.send_message)
        self.chat_process.chat_signals.message_received.connect(self.display_message)
        
        self.add_system_message(f"Чат запущен как {self.process_name}")
    
    def _update_targets(self):
        """Обновление списка доступных получателей из shared_resources"""
        if not self.chat_process.shared_resources:
            return
        
        try:
            # Получаем все процессы со статусом ready или running
            all_states = self.chat_process.shared_resources.get_all_process_states()
            available_targets = [
                name for name, state in all_states.items()
                if name != self.process_name and state.get("status") in ["ready", "running"]
            ]
            
            # Обновляем чекбоксы
            targets_group = self.findChild(QGroupBox, "Отправить:")
            if not targets_group:
                return
            
            targets_layout = targets_group.layout()
            if not targets_layout:
                return
            
            # Удаляем старые чекбоксы
            for target in list(self.target_checkboxes.keys()):
                if target not in available_targets:
                    cb = self.target_checkboxes.pop(target)
                    targets_layout.removeWidget(cb)
                    cb.setParent(None)
                    cb.deleteLater()
            
            # Добавляем новые чекбоксы перед broadcast
            broadcast_index = targets_layout.count() - 1
            for target in available_targets:
                if target not in self.target_checkboxes:
                    cb = QCheckBox(target)
                    cb.setChecked(True)
                    self.target_checkboxes[target] = cb
                    if broadcast_index >= 0:
                        targets_layout.insertWidget(broadcast_index, cb)
                    else:
                        targets_layout.addWidget(cb)
        except Exception as e:
            print(f"Error updating targets: {e}")
    
    def get_selected_targets(self) -> List[str]:
        """Получение выбранных получателей"""
        return [name for name, cb in self.target_checkboxes.items() if cb.isChecked()]
    
    def send_message(self):
        """Отправка сообщения через модули Message и Router"""
        text = self.message_input.text().strip()
        if not text:
            return
        
        # Получаем выбранных получателей
        targets = self.get_selected_targets()
        broadcast_selected = self.broadcast_checkbox.isChecked()
        
        # Проверяем что что-то выбрано
        if not targets and not broadcast_selected:
            self.status_label.setText("Не выбраны получатели!")
            return
        
        try:
            # Если выбрана галочка "отправить всем" - отправляем broadcast
            if broadcast_selected:
                # Создаем broadcast сообщение через модуль Message
                msg = Message.create(
                    type=MessageType.BROADCAST,
                    sender=self.process_name,
                    content={"text": text, "sender": self.process_name},
                    exclude=[self.process_name]
                )
                # Отправляем через роутер
                result = self.chat_process.send(msg)
                if result.get('status') == 'success':
                    self.display_message("Вы", f"[BROADCAST] {text}")
                    self.status_label.setText("Отправлено всем")
            
            # Если выбраны конкретные получатели - отправляем им
            if targets:
                # Создаем сообщение через модуль Message
                msg = Message.create(
                    type=MessageType.GENERAL,
                    sender=self.process_name,
                    targets=targets,
                    content={"text": text, "sender": self.process_name}
                )
                # Отправляем через роутер
                result = self.chat_process.send(msg)
                if result.get('status') == 'success':
                    if not broadcast_selected:
                        self.display_message("Вы", text)
                    self.status_label.setText(f"Отправлено {len(targets)} получателю(ям)")
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")
            print(f"Error sending message: {e}")
        
        self.message_input.clear()
    
    def display_message(self, sender: str, text: str):
        """Отображение сообщения в чате"""
        timestamp = time.strftime("%H:%M:%S")
        
        if sender == "Вы":
            self.chat_display.append(f"[{timestamp}] <b>Вы:</b> {text}")
        else:
            self.chat_display.append(f"[{timestamp}] <span style='color:blue;'>{sender}:</span> {text}")
            
        # Прокрутка вниз
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
    
    def add_system_message(self, text: str):
        """Добавление системного сообщения"""
        self.chat_display.append(f"<i>--- {text} ---</i>")
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        self.update_timer.stop()
        self.chat_process.stop()
        event.accept()