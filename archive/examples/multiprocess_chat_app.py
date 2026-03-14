"""
Упрощенное многопроцессорное приложение чата с использованием готовых модулей.

Архитектура:
- Каждый пользователь работает в отдельном процессе
- PySide6 GUI в главном потоке процесса
- Сообщения отправляются через модули Message и Router
- Используются модули: ProcessModule, Message, Router
"""

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
        # self.update_timer = QTimer()
        # self.update_timer.timeout.connect(self._update_targets)
        # self.update_timer.start(2000)  # Обновление каждые 2 секунды
        
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
        #self._update_targets()  # Первоначальное обновление
        
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
        #self.chat_process.chat_signals.message_received.connect(self.display_message)
        
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

    def send_message(self):
        """Отправка сообщения через модули Message и Router"""
        text = self.message_input.text().strip()    
    
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


class ChatProcess(ProcessModule):
    """
    Процесс чата с простым GUI.
    Использует модули Message и Router для отправки сообщений.
    """
    
    def __init__(self, name: str, shared_resources=None, config: dict = None):
        super().__init__(name, shared_resources, config)
        
        self.chat_signals = None  # Будет создан в GUI потоке
        
        # Регистрируем обработчик команд для получения сообщений
        self.command_adapter.register("chat_message", self._handle_chat_message)
        
        self.log("INFO", f"Chat process {name} initialized", "chat")
    
    def _handle_chat_message(self, data: dict):
        """Обработка входящего чат-сообщения"""
        text = data.get('text', '')
        sender = data.get('sender', 'Unknown')
         
        if text and sender != self.name:
            self.log("INFO", f"Message from {sender}: {text}", "chat")
            if self.chat_signals:
                self.chat_signals.message_received.emit(sender, text)
        
        return {"status": "success", "message": "Message received"}
    
    def run(self):
        """Запуск процесса с GUI"""
        # Сначала запускаем системные потоки (обработка сообщений)
        super().run()
        
        # Создаем GUI в главном потоке процесса
        self._init_gui_in_main_thread()
    
    def _init_gui_in_main_thread(self):
        """Инициализация GUI в главном потоке процесса"""
        try:
            # Создаем QApplication только если его еще нет
            app = QApplication.instance()
            if not app:
                app = QApplication(sys.argv)
            
            # Создаем сигналы
            self.chat_signals = ChatSignals()
            
            # Создаем и показываем окно
            self.chat_window = ChatWindow(self, self.name)
            self.chat_window.show()
            
            self.log("INFO", f"GUI started for {self.name}", "gui")
            
            # Запускаем цикл событий Qt (блокирующий вызов)
            app.exec_()
            
            # Когда окно закрывается, останавливаем процесс
            self.stop()
            
        except Exception as e:
            self.log("ERROR", f"GUI initialization error: {e}", "gui")
            import traceback
            traceback.print_exc()
            self.stop()
    
    def _handle_message(self, message: Dict):
        """
        Обработка входящих сообщений.
        Упрощенная версия - только обработка чат-сообщений.
        """
        try:
            msg_type = message.get('type')
            content = message.get('content', {})
            
            # Обрабатываем обычные сообщения с текстом
            if msg_type in ['general', 'broadcast'] and isinstance(content, dict):
                text = content.get('text')
                sender = content.get('sender')
                
                if text and sender and sender != self.name:
                    # Обрабатываем через command_adapter
                    self.command_adapter.execute("chat_message", {
                        'text': text,
                        'sender': sender
                    })
                    return
            
            # Для остальных сообщений вызываем родительский метод
            super()._handle_message(message)
            
        except Exception as e:
            self.log("ERROR", f"Error handling message: {e}", "chat")
            import traceback
            traceback.print_exc()


def main():
    """
    Главная функция для запуска многопроцессорного чата.
    
    Демонстрирует использование новой архитектуры:
    - SystemLauncher для удобного запуска
    - Загрузка конфигурации из YAML
    - Возможность программной регистрации процессов и воркеров
    """
    from pathlib import Path
    from multiprocess_framework.Process_manager_module import SystemLauncher
    
    # Получаем абсолютный путь к конфигу
    config_path = Path(__file__).parent / 'processes_chat.yaml'

    print(f'config_path {config_path}')
    
    print("=" * 60)
    print("🚀 Multiprocess Chat Application")
    print("=" * 60)
    print(f"📁 Config path: {config_path}")
    print()
    
    # ========================================================================
    # ВАРИАНТ 1: Простой запуск через SystemLauncher
    # ========================================================================
    print("📋 Using SystemLauncher for process management...")
    
    launcher = SystemLauncher()
    
    # Инициализация системы с конфигом
    launcher.initialize_system(str(config_path))
    
    # Запуск всех процессов
    launcher.start()
    
    # ========================================================================
    # ВАРИАНТ 2: Расширенное использование с программной регистрацией
    # ========================================================================
    # Раскомментируйте для демонстрации программной регистрации:
    #
    # # Создаем ProcessManager
    # pm = ProcessManager()
    # 
    # # Загружаем базовый конфиг
    # pm.load_config(str(config_path))
    # 
    # # Программно добавляем дополнительный процесс
    # pm.register_process(
    #     name="Dave",
    #     class_path="src.Test_example.multiprocess_chat_app.ChatProcess",
    #     config={"chat_name": "Дейв"},
    #     priority="normal",
    #     console_config={
    #         "enabled": True,
    #         "title": "Dave Console"
    #     },
    #     queue_config={
    #         "system": {"maxsize": 100},
    #         "data": {"maxsize": 50}
    #     }
    # )
    # 
    # # Добавляем дополнительную очередь для процесса
    # pm.register_queue("Alice", "custom_messages", maxsize=20)
    # 
    # # Регистрируем воркер для процесса (будет загружен при запуске)
    # pm.register_worker(
    #     process_name="Alice",
    #     worker_name="message_processor",
    #     worker_class_path="ChatModule.MessageProcessor",
    #     config={"batch_size": 10},
    #     priority="high"
    # )
    # 
    # # Передаем в Launcher
    # launcher = SystemLauncher(process_manager=pm)
    # launcher.initialize_system()
    # launcher.start()
    
    # ========================================================================
    # Ожидание завершения работы
    # ========================================================================
    try:
        print("\n✅ All processes started. Chat windows should be visible.")
        print("💡 Press Ctrl+C to stop all processes\n")
        
        # Выводим статус системы
        status = launcher.get_status()
        print(f"📊 System status: {len(status)} processes")
        
        # Ожидание завершения
        launcher.wait()
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user, stopping processes...")
        launcher.stop()
        print("✅ All processes stopped")


if __name__ == "__main__":
    main()

