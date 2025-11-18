# chat_process.py
import time
from process_module import ProcessModule
from module_message import MessageFactory, MessageType, CommandMessage
from worker_manager import ThreadConfig, ThreadPriority
from PyQt5.QtCore import QObject, pyqtSignal

# chat_window.py
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QHBoxLayout, QWidget, QTextEdit, QLineEdit, 
                             QPushButton, QLabel, QCheckBox, QGroupBox)
from PyQt5.QtCore import QTimer

class ChatWindow(QMainWindow):
    """Окно чата на PyQt"""
    
    def __init__(self, chat_process: ChatProcess):
        super().__init__()
        self.chat_process = chat_process
        self.setup_ui()
        self.setup_timers()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle(f"Chat - {self.chat_process.name}")
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
        
        # Стартуем чат
        self.chat_process.start_chat()
        self.add_system_message(f"Chat started as {self.chat_process.name}")
        
    def setup_timers(self):
        """Настройка таймеров"""
        # В ProcessModule уже есть потоки для обработки сообщений,
        # поэтому здесь таймер не нужен
        pass
        
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

class ChatSignals(QObject):
    message_received = pyqtSignal(str, str)
    status_updated = pyqtSignal(str)

class ChatProcess(ProcessModule):
    def __init__(self, name: str, process_manager=None, config: dict = None):
        super().__init__(name, process_manager, config)
        
        self.chat_signals = ChatSignals()
        self.known_processes = []
        
        # Регистрируем обработчик чат-команд через CommandManager
        self.command_manager.register_handler("chat_message", self._handle_chat_command)
        
        # Устанавливаем роутер в CommandManager
        self.command_manager.set_router(self.router)
        
        print(f"💬 Chat process {name} initialized")
    
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
            # Регистрируем в QueueRegistry через process_manager
            if self.process_manager:
                self.process_manager.queue_registry.register_process_queues(process_name, process_queues)
            if process_name not in self.known_processes:
                self.known_processes.append(process_name)
            print(f"✅ {self.name} can now send to {process_name}")
    
    def send_chat_message(self, text: str, targets: list) -> bool:
        """Отправка чат-сообщения через команду"""
        result = self.command_manager.send_command(
            command="chat_message",
            args={
                'text': text,
                'sender': self.name,
                'timestamp': time.time()
            },
            targets=targets
        )
        
        if result.get('status') == 'delivered':
            self.log("INFO", f"Sent chat message to {targets}: {text}", "chat")
            self.chat_signals.status_updated.emit(f"Sent to {len(targets)} recipients")
            return True
        else:
            self.log("ERROR", f"Failed to send chat message to {targets}", "chat")
            self.chat_signals.status_updated.emit("Failed to send message")
            return False
    
    def get_available_targets(self):
        """Получение списка доступных получателей"""
        return self.known_processes

# main_chat_dd.py
import sys
import time
import multiprocessing as mp
from PyQt5.QtWidgets import QApplication

from message_router import RouterProcess

def run_chat_process(process_name: str, all_process_queues: dict, router_queues: dict = None):
    """Запуск процесса чата с полной интеграцией менеджеров"""
    app = QApplication(sys.argv)
    
    # Создаем процесс чата
    chat_process = ChatProcess(process_name)
    
    # Регистрируем очереди других процессов
    for other_name, other_queues in all_process_queues.items():
        if other_name != process_name:
            chat_process.register_other_process(other_name, other_queues)
    
    # Регистрируем роутер если есть
    if router_queues:
        chat_process.register_other_process("router", router_queues)
    
    # Создаем и показываем окно
    window = ChatWindow(chat_process)
    window.show()
    
    return app.exec_()

def run_router_process(router_name: str, all_process_queues: dict):
    """Запуск процесса маршрутизации"""
    app = QApplication(sys.argv)  # Для совместимости, но роутер может работать без GUI
    
    router_process = RouterProcess(router_name)
    
    # Регистрируем все процессы в роутере
    for process_name, process_queues in all_process_queues.items():
        router_process.register_process(process_name, process_queues)
    
    router_process.start_routing()
    
    # Роутер может работать без окна, или можно создать простой мониторинг
    print(f"🔄 Router {router_name} is running...")
    
    # Простой цикл для демонстрации
    try:
        while True:
            stats = router_process.get_stats()
            print(f"📊 Router stats: {stats}")
            time.sleep(5)
    except KeyboardInterrupt:
        router_process.stop()
    
    return 0

if __name__ == "__main__":
    print("🚀 Starting DD Architecture Chat System...")
    
    # Создаем очереди для всех процессов
    process_queues = {}
    process_names = ["Alice", "Bob", "Charlie"]
    
    for name in process_names:
        process_queues[name] = {
            'system': mp.Queue(),
            'data': mp.Queue(),
            'broadcast': mp.Queue(),
            'custom': mp.Queue()
        }
    
    # Очереди для роутера
    router_queues = {
        'system': mp.Queue(),
        'data': mp.Queue(),
        'broadcast': mp.Queue(),
        'custom': mp.Queue()
    }
    
    # Запускаем процессы
    processes = []
    
    # Запускаем роутер (опционально)
    use_dedicated_router = False  # Меняйте на True для тестирования выделенного роутера
    
    if use_dedicated_router:
        router_process = mp.Process(
            target=run_router_process,
            args=("main_router", process_queues),
            name="RouterProcess"
        )
        router_process.start()
        processes.append(router_process)
        print("✅ Started dedicated router")
        time.sleep(1)
    
    # Запускаем чат-процессы
    for name in process_names:
        process = mp.Process(
            target=run_chat_process,
            args=(name, process_queues, router_queues if use_dedicated_router else None),
            name=f"Chat-{name}"
        )
        process.start()
        processes.append(process)
        print(f"✅ Started {name}")
        time.sleep(0.5)
        
    print("💬 DD Architecture Chat System is running!")
    print("✅ Features:")
    print("  • Full ProcessModule integration")
    print("  • SystemMessage classes usage") 
    print("  • Manager collaboration (Command, Worker, Logger, Router)")
    print("  • Optional dedicated router process")
    print("  • Checkbox recipient selection")
    
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        for process in processes:
            if process.is_alive():
                process.terminate()
                
    print("🎯 DD Architecture Chat System stopped")