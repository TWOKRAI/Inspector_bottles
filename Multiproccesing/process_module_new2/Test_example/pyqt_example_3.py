import time
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QHBoxLayout, QWidget, QTextEdit, QLineEdit, 
                             QPushButton, QLabel, QCheckBox, QGroupBox)
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from Process_module.process_module import ProcessModule
from Worker_module.worker_manager import ThreadConfig, ThreadPriority


class ChatSignals(QObject):
    message_received = pyqtSignal(str, str)
    status_updated = pyqtSignal(str)

class ChatWindow(QMainWindow):
    """Окно чата на PyQt - работает в потоке GUI"""
    
    def __init__(self, chat_process, process_name: str):
        super().__init__()
        self.chat_process = chat_process
        self.process_name = process_name
        self.setup_ui()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle(f"Chat - {self.process_name}")
        self.setGeometry(100, 100, 500, 400)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Группа выбора получателей
        targets_group = QGroupBox("Send to:")
        targets_layout = QVBoxLayout(targets_group)
        
        self.target_checkboxes = {}
        available_targets = self.chat_process.get_available_targets()
        
        for target in available_targets:
            cb = QCheckBox(target)
            cb.setChecked(True)
            self.target_checkboxes[target] = cb
            targets_layout.addWidget(cb)
        
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
        self.chat_process.chat_signals.message_received.connect(self.display_message)
        self.chat_process.chat_signals.status_updated.connect(self.status_label.setText)
        
        self.add_system_message(f"Chat started as {self.process_name}")
        
    def get_selected_targets(self):
        """Получение выбранных получателей"""
        return [name for name, cb in self.target_checkboxes.items() if cb.isChecked()]
        
    def send_message(self):
        """Отправка сообщения"""
        text = self.message_input.text().strip()
        if text:
            targets = self.get_selected_targets()
            
            if not targets:
                self.status_label.setText("No recipients selected!")
                return
                
            success = self.chat_process.send_chat_message(text, targets)
            
            if success:
                self.display_message("You", text)
                self.message_input.clear()
        
    def display_message(self, sender: str, text: str):
        """Отображение сообщения в чате"""
        timestamp = time.strftime("%H:%M:%S")
        
        if sender == "You":
            self.chat_display.append(f"[{timestamp}] You: {text}")
        else:
            self.chat_display.append(f"[{timestamp}] {sender}: {text}")
            
        # Прокрутка вниз
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_display.setTextCursor(cursor)
        
    def add_system_message(self, text: str):
        """Добавление системного сообщения"""
        self.chat_display.append(f"--- {text} ---")
        
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        self.chat_process.stop()
        event.accept()

class ChatProcess(ProcessModule):
    """
    Процесс чата, который содержит:
    - GUI поток (ChatWindow)
    - Поток обработки сообщений
    """
    
    def __init__(self, name: str, process_manager=None, config: dict = None):
        super().__init__(name, process_manager, config)
        
        self.chat_signals = ChatSignals()
        self.known_processes = []
        
        # Регистрируем обработчик чат-команд
        self.command_manager.register_handler("chat_message", self._handle_chat_command)
        
        print(f"💬 Chat process {name} initialized")
    
    def _init_application_threads(self):
        """Инициализация потоков приложения для чата"""
        # Поток для GUI
        self.worker_manager.create_worker(
            "gui_thread",
            self._gui_loop,
            ThreadConfig(priority=ThreadPriority.HIGH),
            auto_start=True
        )
        
        # Поток для обработки чат-сообщений
        self.worker_manager.create_worker(
            "chat_processor",
            self._chat_processing_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True
        )
    
    def _gui_loop(self, stop_event, pause_event):
        """Цикл GUI - создает и запускает окно чата"""
        # Создаем QApplication только если его еще нет
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        # Создаем и показываем окно
        self.chat_window = ChatWindow(self, self.name)
        self.chat_window.show()
        
        # Запускаем цикл событий
        print(f"🎨 Starting GUI for {self.name}")
        app.exec_()
        
        # Когда окно закрывается, останавливаем процесс
        self.stop()
    
    def _chat_processing_loop(self, stop_event, pause_event):
        """Дополнительная обработка чат-сообщений"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            # Здесь может быть дополнительная логика обработки сообщений
            time.sleep(0.1)
    
    def _handle_chat_command(self, args):
        """Обработка чат-команды"""
        text = args.get('text', '')
        sender = args.get('sender', 'Unknown')
        
        if text and sender != self.name:
            print(f"💬 {self.name} received from {sender}: {text}")
            self.chat_signals.message_received.emit(sender, text)
            self.log("INFO", f"Chat message from {sender}: {text}", "chat")
    
    def register_other_process(self, process_name: str, process_queues: dict):
        """Регистрация другого процесса для обмена сообщениями"""
        if process_name != self.name and 'system' in process_queues:
            self.router.register_queue(process_name, process_queues['system'])
            if process_name not in self.known_processes:
                self.known_processes.append(process_name)
            print(f"✅ {self.name} can now send to {process_name}")
    
    def send_chat_message(self, text: str, targets: list) -> bool:
        """Отправка чат-сообщения через команду"""
        command_msg = self.message_manager.create_general_message(
            self.name,
            "chat_message",
            {
                'text': text,
                'sender': self.name,
                'timestamp': time.time()
            },
            target=targets[0] if len(targets) == 1 else "all"
        )
        
        success = self.send_message(command_msg, targets)
        
        if success:
            self.log("INFO", f"Sent chat message to {targets}: {text}", "chat")
            self.chat_signals.status_updated.emit(f"Sent to {len(targets)} recipients")
        else:
            self.log("ERROR", f"Failed to send chat message to {targets}", "chat")
            self.chat_signals.status_updated.emit("Failed to send message")
            
        return success
    
    def get_available_targets(self):
        """Получение списка доступных получателей"""
        return self.known_processes
    
    def start_chat(self):
        """Запуск чата"""
        print(f"🚀 Chat {self.name} starting...")
        self.run()
        print(f"✅ Chat {self.name} started")