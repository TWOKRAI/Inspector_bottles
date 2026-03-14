import time
import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QHBoxLayout, QWidget, QTextEdit, QLineEdit, 
                             QPushButton, QLabel, QCheckBox, QGroupBox)
from PySide6.QtCore import QObject, Signal, QTimer


from multiprocess_framework.Process_module.process_module import ProcessModule
from multiprocess_framework.Worker_module.worker_manager import ThreadConfig, ThreadPriority


class ChatSignals(QObject):
    """Сигналы для PyQt GUI"""
    message_received = Signal(str, str)
    status_updated = Signal(str)


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
        self.chat_process.chat_signals.message_received.connect(self.display_message)
        self.chat_process.chat_signals.status_updated.connect(self.status_label.setText)
        
        self.add_system_message(f"Chat started as {self.process_name}")
        
    def get_selected_targets(self):
        """Получение выбранных получателей"""
        return [name for name, cb in self.target_checkboxes.items() if cb.isChecked()]
        
    def send_message(self):
        """Отправка сообщения"""
        text = self.message_input.text().strip()
        if not text:
            return
            
        # Проверяем режим broadcast
        if self.broadcast_checkbox.isChecked():
            success = self.chat_process.broadcast_chat_message(text)
            if success:
                self.display_message("You", f"[BROADCAST] {text}")
                self.status_label.setText(f"Broadcast sent")
        else:
            targets = self.get_selected_targets()
            
            if not targets:
                self.status_label.setText("No recipients selected!")
                return
                
            success = self.chat_process.send_chat_message(text, targets)
            
            if success:
                self.display_message("You", text)
                self.status_label.setText(f"Sent to {len(targets)} recipient(s)")
        
        self.message_input.clear()
        
    def display_message(self, sender: str, text: str):
        """Отображение сообщения в чате"""
        timestamp = time.strftime("%H:%M:%S")
        
        if sender == "You":
            self.chat_display.append(f"[{timestamp}] <b>You:</b> {text}")
        else:
            self.chat_display.append(f"[{timestamp}] <span style='color:blue;'>{sender}:</span> {text}")
            
        # Прокрутка вниз
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_display.setTextCursor(cursor)
        
    def add_system_message(self, text: str):
        """Добавление системного сообщения"""
        self.chat_display.append(f"<i>--- {text} ---</i>")
        
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
    
    def __init__(self, name: str, interaction_manager=None, config: dict = None):
        super().__init__(name, interaction_manager, config)
        
        self.chat_signals = None  # Будет создан в GUI потоке
        self.known_processes = []
        
        # Регистрируем обработчик чат-команд через адаптер
        self.command_adapter.register("chat_message", self._handle_chat_command)
        
        self.log("INFO", f"Chat process {name} initialized", "chat")
    
    def _init_application_threads(self):
        """Инициализация потоков приложения для чата"""
        # Поток для GUI
        config = ThreadConfig(priority=ThreadPriority.REALTIME)
        self.worker_manager.create_worker(
            "gui_thread",
            self._gui_loop,
            config,
            auto_start=True
        )
    
    def _gui_loop(self, stop_event, pause_event):
        """Цикл GUI - создает и запускает окно чата"""
        # Создаем QApplication только если его еще нет
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        # Создаем сигналы ТОЛЬКО в GUI потоке
        self.chat_signals = ChatSignals()
        
        # Создаем и показываем окно
        self.chat_window = ChatWindow(self, self.name)
        self.chat_window.show()
        
        # Запускаем цикл событий
        self.log("INFO", f"Starting GUI for {self.name}", "gui")
        app.exec_()
        
        # Когда окно закрывается, останавливаем процесс
        self.stop()
    
    def _handle_chat_command(self, data: dict):
        """Обработка чат-команды"""
        text = data.get('text', '')
        sender = data.get('sender', 'Unknown')
        
        if text and sender != self.name:
            self.log("INFO", f"Message from {sender}: {text}", "chat")
            if self.chat_signals:
                self.chat_signals.message_received.emit(sender, text)
            
        return {"status": "success", "message": "Message received"}
    
    def register_other_process(self, process_name: str):
        """Регистрация другого процесса для обмена сообщениями"""
        if process_name != self.name and process_name not in self.known_processes:
            self.known_processes.append(process_name)
            self.log("DEBUG", f"Registered process: {process_name}", "chat")
    
    def send_chat_message(self, text: str, targets: list) -> bool:
        """Отправка чат-сообщения"""
        try:
            # Создаем командное сообщение через адаптер
            cmd_msg = self.message_adapter.create_command(
                command="chat_message",
                args={
                    'text': text,
                    'sender': self.name,
                    'timestamp': time.time()
                },
                targets=targets
            )
            
            if not cmd_msg:
                self.log("ERROR", "Failed to create message", "chat")
                return False
            
            # Отправляем каждому получателю
            success_count = 0
            for target in targets:
                if self.router_adapter.send_to_process(target, cmd_msg.to_dict()):
                    success_count += 1
            
            if success_count > 0:
                self.log("INFO", f"Sent to {success_count}/{len(targets)} recipients", "chat")
                if self.chat_signals:
                    self.chat_signals.status_updated.emit(f"Sent to {success_count} recipients")
                return True
            else:
                self.log("ERROR", "Failed to send to any recipients", "chat")
                if self.chat_signals:
                    self.chat_signals.status_updated.emit("Failed to send message")
                return False
                
        except Exception as e:
            self.log("ERROR", f"Send error: {e}", "chat")
            return False
    
    def broadcast_chat_message(self, text: str) -> bool:
        """Рассылка чат-сообщения всем процессам"""
        try:
            # Создаем командное сообщение
            cmd_msg = self.message_adapter.create_command(
                command="chat_message",
                args={
                    'text': text,
                    'sender': self.name,
                    'timestamp': time.time()
                },
                targets=["all"]  # Broadcast marker
            )
            
            if not cmd_msg:
                return False
            
            # Отправляем через broadcast
            count = self.router_adapter.broadcast(cmd_msg.to_dict(), exclude_self=True)
            
            self.log("INFO", f"Broadcast to {count} processes", "chat")
            if self.chat_signals and count > 0:
                self.chat_signals.status_updated.emit(f"Broadcast to {count} processes")
            return count > 0
            
        except Exception as e:
            self.log("ERROR", f"Broadcast error: {e}", "chat")
            return False
    
    def get_available_targets(self):
        """Получение списка доступных получателей"""
        return self.known_processes
    
    def start_chat(self):
        """Запуск чата"""
        self.log("INFO", f"Chat {self.name} starting...", "lifecycle")
        self.run()


class RouterProcess(ProcessModule):
    """
    Специализированный процесс для маршрутизации сообщений.
    Разгружает другие процессы от рассылки.
    """
    
    def __init__(self, name: str, interaction_manager=None, config: dict = None):
        super().__init__(name, interaction_manager, config)
        
        self.routing_stats = {
            "total": 0,
            "success": 0,
            "errors": 0
        }
        
        self.log("INFO", f"Router process initialized", "router")
    
    def _init_application_threads(self):
        """Инициализация специализированных потоков роутера"""
        # Высокоприоритетный поток маршрутизации
        config = ThreadConfig(priority=ThreadPriority.REALTIME)
        self.worker_manager.create_worker(
            "routing_loop",
            self._routing_loop,
            config,
            auto_start=True
        )
    
    def _routing_loop(self, stop_event, pause_event):
        """Основной цикл маршрутизации"""
        self.log("INFO", "Routing loop started", "router")
        
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                # Получаем входящие сообщения
                messages = self.router_adapter.poll_messages()
                
                for message in messages:
                    self._route_message(message)
                
                time.sleep(0.01)  # Небольшая задержка
                
            except Exception as e:
                self.log("ERROR", f"Routing loop error: {e}", "router")
                time.sleep(0.1)
    
    def _route_message(self, message: dict):
        """Маршрутизация сообщения к целям"""
        try:
            targets = message.get('targets', [])
            
            if not targets:
                return
            
            # Рассылаем всем целям
            success_count = 0
            for target in targets:
                if self.router_adapter.send_to_process(target, message):
                    success_count += 1
            
            self.routing_stats["total"] += 1
            self.routing_stats["success"] += success_count
            
            if success_count < len(targets):
                self.routing_stats["errors"] += (len(targets) - success_count)
            
        except Exception as e:
            self.log("ERROR", f"Routing failed: {e}", "router")
            self.routing_stats["errors"] += 1
    
    def get_routing_stats(self):
        """Получение статистики маршрутизации"""
        return self.routing_stats.copy()


def test_chat_system():
    """Тестирование системы чатов"""
    print("=" * 60)
    print("🚀 Starting Chat System Test")
    print("=" * 60)
    
    from multiprocess_framework.Process_manager_module.Processes_Manager import ProcessManager
    
    # Создаем ProcessManager
    pm = ProcessManager()
    
    # Имена процессов
    chat_names = ["Alice", "Bob", "Charlie"]
    
    # Создаем процессы чатов
    print("\n📦 Creating chat processes...")
    for name in chat_names:
        process = pm.create_os_process(
            process_class=ChatProcess,
            name=name,
            priority='high'
        )
        pm.os_processes.append(process)
        print(f"  ✅ Created: {name}")
    
    # Создаем процесс роутера (опционально)
    # Раскомментируйте если нужен выделенный роутер
    # print("\n📦 Creating router process...")
    # router_process = pm.create_os_process(
    #     process_class=RouterProcess,
    #     name="Router",
    #     priority='high'
    # )
    # pm.os_processes.append(router_process)
    # print("  ✅ Created: Router")
    
    # Запускаем все процессы
    print("\n🚀 Starting all processes...")
    pm.start_processes()
    
    # Ждем небольшую инициализацию
    time.sleep(1)
    
    # Регистрируем процессы друг у друга
    print("\n🔗 Cross-registering processes...")
    for proc in pm.process_instances:
        if hasattr(proc, 'register_other_process'):
            for other_name in chat_names:
                if other_name != proc.name:
                    proc.register_other_process(other_name)
    
    print("\n" + "=" * 60)
    print("✅ System is ready!")
    print("=" * 60)
    print("\n💬 Chat windows are open. You can now:")
    print("  - Send messages to specific users")
    print("  - Use 'Broadcast to All' to send to everyone")
    print("  - Close any window to stop that process")
    print("\nPress Ctrl+C to stop all processes")
    print("=" * 60 + "\n")
    
    # Ждем завершения
    try:
        pm.wait_for_processes()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping all processes...")
        pm.stop_processes()
        print("✅ All processes stopped")


if __name__ == "__main__":
    test_chat_system()
