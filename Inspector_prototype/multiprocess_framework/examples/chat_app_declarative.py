"""
Улучшенный пример многопроцессного чата с декларативным подходом.

Демонстрирует:
1. Декораторы (@process, @worker) для декларативного определения процессов
2. Классы-конфигурации (ProcessConfig) для программного создания
3. Улучшенное взаимодействие процессов через ProcessManager
4. Выбор получателей сообщений из списка доступных процессов
5. Экспорт конфигов из ProcessData

Архитектура:
- Каждый пользователь работает в отдельном процессе
- PySide6 GUI в главном потоке процесса
- Сообщения отправляются через модули Message и Router
- ProcessManager управляет всеми процессами и их взаимодействием
"""

import sys
import time
from typing import List, Dict, Optional
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
    QWidget, QTextEdit, QLineEdit, QPushButton, QLabel, 
    QCheckBox, QGroupBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QTextCursor

from multiprocess_framework import ProcessModule, Message, MessageType, process, worker, ProcessDataKeys


class ChatSignals(QObject):
    """Сигналы для PySide6 GUI"""
    message_received = Signal(str, str)  # sender, text
    recipients_updated = Signal(list)  # список доступных получателей


@process(name="ChatProcess", priority="normal")
class ChatProcess(ProcessModule):
    """
    Процесс чата с декларативным определением через декораторы.
    
    Использует @process для определения метаданных процесса
    и @worker для определения воркеров.
    """
    
    def __init__(self, name: str, shared_resources=None, config: dict = None):
        super().__init__(name, shared_resources, config)
        
        self.chat_signals = None  # Будет создан в GUI потоке
        
        # Регистрируем обработчик команд для получения сообщений
        self.command_adapter.register("chat_message", self._handle_chat_message)
        
        # Таймер для обновления списка получателей
        self.recipients_update_timer = None
        
        self.log("INFO", f"Chat process {name} initialized", "chat")
    
    @worker(name="message_handler", priority="normal")
    def handle_messages(self):
        """
        Воркер для обработки входящих сообщений.
        
        Декорирован @worker для автоматической регистрации.
        """
        while not self.should_stop():
            try:
                # Получаем сообщения из роутера
                messages = self.router_manager.receive(
                    channel='general',
                    timeout=0.1
                )
                
                for message in messages:
                    self._process_message(message)
                    
            except Exception as e:
                self.log("ERROR", f"Error handling messages: {e}", "chat")
                time.sleep(0.1)
    
    def _process_message(self, message: Dict):
        """Обработка входящего сообщения."""
        try:
            msg_type = message.get('type')
            content = message.get('content', {})
            sender = message.get('sender')
            
            # Обрабатываем чат-сообщения
            if msg_type in ['general', 'broadcast'] and isinstance(content, dict):
                text = content.get('text')
                
                if text and sender and sender != self.name:
                    self.log("INFO", f"Message from {sender}: {text}", "chat")
                    if self.chat_signals:
                        self.chat_signals.message_received.emit(sender, text)
            
            # Обрабатываем системные сообщения о изменении статусов процессов
            elif msg_type == 'system' and content.get('subtype') == 'process_status_changed':
                # Обновляем список получателей при изменении статусов
                self._update_recipients_list()
        
        except Exception as e:
            self.log("ERROR", f"Error processing message: {e}", "chat")
    
    def _handle_chat_message(self, data: dict):
        """Обработка входящего чат-сообщения через command_adapter."""
        text = data.get('text', '')
        sender = data.get('sender', 'Unknown')
        
        if text and sender != self.name:
            self.log("INFO", f"Message from {sender}: {text}", "chat")
            if self.chat_signals:
                self.chat_signals.message_received.emit(sender, text)
        
        return {"status": "success", "message": "Message received"}
    
    def _update_recipients_list(self):
        """Обновление списка доступных получателей."""
        if not self.shared_resources or not self.chat_signals:
            return
        
        try:
            # Получаем все процессы со статусом ready или running
            all_states = self.shared_resources.get_all_process_states()
            available_recipients = [
                name for name, state in all_states.items()
                if name != self.name and state.get("status") in ["ready", "running"]
            ]
            
            if self.chat_signals:
                self.chat_signals.recipients_updated.emit(available_recipients)
        
        except Exception as e:
            self.log("ERROR", f"Error updating recipients: {e}", "chat")
    
    def send_message(self, text: str, recipients: Optional[List[str]] = None, broadcast: bool = False):
        """
        Отправка сообщения через роутер.
        
        Args:
            text: Текст сообщения
            recipients: Список получателей (если None и broadcast=False, отправка не выполняется)
            broadcast: Отправить всем процессам
        """
        if not text.strip():
            return
        
        try:
            if broadcast:
                # Широковещательная отправка
                message = {
                    "type": "broadcast",
                    "sender": self.name,
                    "content": {
                        "text": text,
                        "sender": self.name
                    }
                }
                self.broadcast_message(message, exclude_self=False)
                self.log("INFO", f"Broadcast message: {text}", "chat")
            
            elif recipients:
                # Отправка конкретным получателям
                for recipient in recipients:
                    message = {
                        "type": "general",
                        "sender": self.name,
                        "target": recipient,
                        "content": {
                            "text": text,
                            "sender": self.name
                        }
                    }
                    self.send(message)
                    self.log("INFO", f"Message to {recipient}: {text}", "chat")
        
        except Exception as e:
            self.log("ERROR", f"Error sending message: {e}", "chat")
    
    def run(self):
        """Запуск процесса с GUI."""
        # Сначала запускаем системные потоки (обработка сообщений)
        super().run()
        
        # Создаем GUI в главном потоке процесса
        self._init_gui_in_main_thread()
    
    def _init_gui_in_main_thread(self):
        """Инициализация GUI в главном потоке процесса."""
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
            
            # Настраиваем таймер для обновления списка получателей
            self.recipients_update_timer = QTimer()
            self.recipients_update_timer.timeout.connect(self._update_recipients_list)
            self.recipients_update_timer.start(2000)  # Обновление каждые 2 секунды
            
            # Первоначальное обновление списка
            self._update_recipients_list()
            
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


class ChatWindow(QMainWindow):
    """Улучшенное окно чата с выбором получателей."""
    
    def __init__(self, chat_process: ChatProcess, process_name: str):
        super().__init__()
        self.chat_process = chat_process
        self.process_name = process_name
        self.selected_recipients = []
        self.setup_ui()
        
        # Подключаем сигналы
        if chat_process.chat_signals:
            chat_process.chat_signals.message_received.connect(self.display_message)
            chat_process.chat_signals.recipients_updated.connect(self.update_recipients_list)
        
        self.add_system_message(f"Чат запущен как {self.process_name}")
    
    def setup_ui(self):
        """Настройка интерфейса."""
        self.setWindowTitle(f"Chat - {self.process_name}")
        self.setGeometry(100, 100, 700, 600)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Группа выбора получателей
        recipients_group = QGroupBox("Получатели:")
        recipients_layout = QVBoxLayout(recipients_group)
        
        # Список получателей с чекбоксами
        self.recipients_list = QListWidget()
        self.recipients_list.setMaximumHeight(150)
        recipients_layout.addWidget(self.recipients_list)
        
        # Кнопка "Broadcast to All"
        self.broadcast_checkbox = QCheckBox("Отправить всем (Broadcast)")
        recipients_layout.addWidget(self.broadcast_checkbox)
        
        layout.addWidget(recipients_group)
        
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
        self.broadcast_checkbox.stateChanged.connect(self._on_broadcast_changed)
    
    def _on_broadcast_changed(self, state):
        """Обработка изменения состояния чекбокса Broadcast."""
        if state:
            # Отключаем выбор получателей при включении broadcast
            for i in range(self.recipients_list.count()):
                item = self.recipients_list.item(i)
                item.setCheckState(0)  # Uncheck all
        else:
            # Включаем выбор получателей при выключении broadcast
            pass
    
    def update_recipients_list(self, recipients: List[str]):
        """Обновление списка доступных получателей."""
        self.recipients_list.clear()
        
        for recipient in recipients:
            item = QListWidgetItem(recipient)
            item.setCheckState(0)  # Unchecked by default
            self.recipients_list.addItem(item)
        
        self.status_label.setText(f"Доступно получателей: {len(recipients)}")
    
    def send_message(self):
        """Отправка сообщения."""
        text = self.message_input.text().strip()
        if not text:
            return
        
        # Определяем получателей
        broadcast = self.broadcast_checkbox.isChecked()
        recipients = []
        
        if not broadcast:
            # Собираем выбранных получателей
            for i in range(self.recipients_list.count()):
                item = self.recipients_list.item(i)
                if item.checkState() == 2:  # Checked
                    recipients.append(item.text())
        
        # Отправляем сообщение
        self.chat_process.send_message(text, recipients=recipients if recipients else None, broadcast=broadcast)
        
        # Отображаем свое сообщение
        self.display_message("Вы", text)
        
        # Очищаем поле ввода
        self.message_input.clear()
    
    def display_message(self, sender: str, text: str):
        """Отображение сообщения в чате."""
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
        """Добавление системного сообщения."""
        self.chat_display.append(f"<i>--- {text} ---</i>")
    
    def closeEvent(self, event):
        """Обработка закрытия окна."""
        if self.chat_process.recipients_update_timer:
            self.chat_process.recipients_update_timer.stop()
        self.chat_process.stop()
        event.accept()


def main():
    """
    Главная функция для запуска многопроцессорного чата.
    
    Демонстрирует использование нового декларативного подхода:
    - Декораторы для определения процессов
    - Классы-конфигурации для программного создания
    - Улучшенное взаимодействие через ProcessManager
    """
    from pathlib import Path
    from multiprocess_framework import SystemLauncher, ProcessConfig, QueueConfig, ConsoleConfig
    
    print("=" * 60)
    print("🚀 Multiprocess Chat Application (Declarative)")
    print("=" * 60)
    print()
    
    # ========================================================================
    # ВАРИАНТ 1: Декларативный подход через классы-конфигурации
    # ========================================================================
    print("📋 Using declarative approach with ProcessConfig...")
    
    # Создаем конфигурации процессов через классы-конфигурации
    alice_config = ProcessConfig(
        name="Alice",
        class_path="examples.chat_app_declarative.ChatProcess",
        priority="normal",
        queues={
            "system": QueueConfig(maxsize=100),
            "data": QueueConfig(maxsize=50)
        },
        console=ConsoleConfig(enabled=True, title="Alice Console")
    )
    
    bob_config = ProcessConfig(
        name="Bob",
        class_path="examples.chat_app_declarative.ChatProcess",
        priority="normal",
        queues={
            "system": QueueConfig(maxsize=100),
            "data": QueueConfig(maxsize=50)
        },
        console=ConsoleConfig(enabled=True, title="Bob Console")
    )
    
    # Инициализация системы с конфигами
    configs_dict = {
        "Alice": alice_config.to_dict(),
        "Bob": bob_config.to_dict()
    }
    
    launcher = SystemLauncher()
    launcher.initialize_system(configs_dict)
    
    # Запуск всех процессов
    launcher.start()
    
    # ========================================================================
    # Ожидание завершения работы
    # ========================================================================
    try:
        print("\n✅ All processes started. Chat windows should be visible.")
        print("💡 Press Ctrl+C to stop all processes\n")
        
        # Выводим статус системы
        status = launcher.get_status()
        print(f"📊 System status: {len(status.get('registered_processes', []))} processes")
        
        # Ожидание завершения
        launcher.wait()
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user, stopping processes...")
        launcher.stop()
        print("✅ All processes stopped")


if __name__ == "__main__":
    main()

