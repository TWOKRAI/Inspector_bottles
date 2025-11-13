# broadcast_chat.py
import sys
import time
import multiprocessing as mp
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, 
                             QHBoxLayout, QWidget, QTextEdit, QLineEdit, 
                             QPushButton, QLabel, QStatusBar)
from PyQt5.QtCore import QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QTextCursor

class ChatSignals(QObject):
    message_received = pyqtSignal(str, str)
    status_updated = pyqtSignal(str)

class BroadcastChatProcess:
    def __init__(self, name: str, all_queues: dict, my_queue: mp.Queue):
        self.name = name
        self.all_queues = all_queues  # Словарь всех очередей {name: queue}
        self.my_queue = my_queue      # Моя личная очередь для входящих
        self.signals = ChatSignals()
        self.is_running = False
        
    def start(self):
        self.is_running = True
        print(f"[{self.name}] Process started with {len(self.all_queues)} queues")
        
    def stop(self):
        self.is_running = False
        print(f"[{self.name}] Process stopped")
        
    def send_message(self, text: str):
        """Отправка сообщения во ВСЕ очереди (кроме своей)"""
        message_data = {
            'sender': self.name,
            'message': text,
            'timestamp': time.time()
        }
        
        sent_count = 0
        for queue_name, queue in self.all_queues.items():
            if queue_name != self.name:  # Не отправляем себе
                try:
                    queue.put(message_data)
                    sent_count += 1
                    print(f"[{self.name}] Sent to {queue_name}: '{text}'")
                except Exception as e:
                    print(f"[{self.name}] Send error to {queue_name}: {e}")
        
        print(f"[{self.name}] Broadcast complete: {sent_count}/{len(self.all_queues)-1} queues")
            
    def check_messages(self):
        """Проверка входящих сообщений из ЛИЧНОЙ очереди"""
        if not self.is_running:
            return
            
        try:
            # Обрабатываем ВСЕ сообщения в личной очереди
            processed = 0
            while not self.my_queue.empty():
                message = self.my_queue.get_nowait()
                processed += 1
                
                sender = message.get('sender', 'Unknown')
                text = message.get('message', '')
                
                # Всегда показываем, кроме своих (но своих тут быть не должно)
                if sender != self.name and text:  # Игнорируем пустые сообщения
                    print(f"[{self.name}] Received from {sender}: '{text}'")
                    self.signals.message_received.emit(sender, text)
                    
            if processed > 0:
                print(f"[{self.name}] Processed {processed} messages")
                
        except Exception as e:
            print(f"[{self.name}] Queue error: {e}")

class BroadcastChatWindow(QMainWindow):
    def __init__(self, process_name: str, all_queues: dict, my_queue: mp.Queue):
        super().__init__()
        self.process_name = process_name
        self.chat_process = BroadcastChatProcess(process_name, all_queues, my_queue)
        self.setup_ui()
        self.setup_timers()
        
    def setup_ui(self):
        self.setWindowTitle(f"Broadcast Chat - {self.process_name}")
        self.setGeometry(100, 100, 500, 400)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Статус бар
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(f"Ready - Connected to {len(self.chat_process.all_queues)} processes")
        
        # Отображение чата
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)
        layout.addWidget(self.chat_display)
        
        # Панель ввода
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type your message... (will broadcast to ALL)")
        self.send_button = QPushButton("Broadcast")
        
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)
        
        # Информация о подключениях
        self.connections_label = QLabel(f"Connected to: {', '.join([name for name in self.chat_process.all_queues.keys() if name != self.process_name])}")
        layout.addWidget(self.connections_label)
        
        # Подключение сигналов
        self.send_button.clicked.connect(self.send_message)
        self.message_input.returnPressed.connect(self.send_message)
        self.chat_process.signals.message_received.connect(self.display_message)
        self.chat_process.signals.status_updated.connect(self.status_bar.showMessage)
        
        # Запуск процесса
        self.chat_process.start()
        self.add_system_message(f"Broadcast chat started as {self.process_name}")
        self.add_system_message(f"Connected to {len(self.chat_process.all_queues)-1} other processes")
        
    def setup_timers(self):
        """Таймер для мгновенной проверки сообщений"""
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_messages)
        self.check_timer.start(20)  # Проверка каждые 20ms
        
    def check_messages(self):
        self.chat_process.check_messages()
        
    def send_message(self):
        text = self.message_input.text().strip()
        if text:
            self.chat_process.send_message(text)
            self.display_message("You", text)
            self.message_input.clear()
            self.status_bar.showMessage(f"Broadcasted: '{text}'")
            
    def display_message(self, sender: str, text: str):
        timestamp = time.strftime("%H:%M:%S")
        
        if sender == "You":
            formatted = f"""
            <div style='margin: 10px 0;'>
                <div style='text-align: right; color: #6c757d; font-size: 12px;'>{timestamp} (broadcast)</div>
                <div style='background: #007bff; color: white; padding: 8px 12px; border-radius: 18px 18px 4px 18px; margin-left: 60px; text-align: right;'>
                    <b>You:</b> {text}
                </div>
            </div>
            """
        else:
            formatted = f"""
            <div style='margin: 10px 0;'>
                <div style='text-align: left; color: #6c757d; font-size: 12px;'>{timestamp} • {sender}</div>
                <div style='background: #28a745; color: white; padding: 8px 12px; border-radius: 18px 18px 18px 4px; margin-right: 60px;'>
                    <b>{sender}:</b> {text}
                </div>
            </div>
            """
            
        self.chat_display.append(formatted)
        self.chat_display.moveCursor(QTextCursor.End)
        
    def add_system_message(self, text: str):
        self.chat_display.append(f"""
        <div style='text-align: center; color: #6c757d; font-style: italic; margin: 10px 0; padding: 5px; background: #fff3cd; border-radius: 5px;'>
            {text}
        </div>
        """)
        self.chat_display.moveCursor(QTextCursor.End)
        
    def closeEvent(self, event):
        self.chat_process.stop()
        event.accept()

def run_broadcast_chat(process_name: str, all_queues: dict, my_queue: mp.Queue):
    app = QApplication(sys.argv)
    window = BroadcastChatWindow(process_name, all_queues, my_queue)
    window.show()
    return app.exec_()

if __name__ == "__main__":
    print("🚀 Starting BROADCAST Chat System...")
    print("📡 Each message will be sent to ALL processes")
    print("🔧 Fixed: No more lost messages!")
    
    # Создаем отдельную очередь для КАЖДОГО процесса
    process_queues = {
        "Alice": mp.Queue(),
        "Bob": mp.Queue(), 
        "Charlie": mp.Queue()
    }
    
    processes = []
    
    for name, queue in process_queues.items():
        process = mp.Process(
            target=run_broadcast_chat,
            args=(name, process_queues, queue),  # Передаем ВСЕ очереди и личную очередь
            name=f"BroadcastChat-{name}"
        )
        process.start()
        processes.append(process)
        print(f"✅ Started {name} with personal queue")
        time.sleep(0.3)  # Короткая задержка
        
    print("💬 BROADCAST chat system is running!")
    print("📨 Every message will appear in ALL windows instantly")
    print("🔗 Architecture: Each process has its own incoming queue")
    
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        for process in processes:
            if process.is_alive():
                process.terminate()
                
    print("🎯 Broadcast chat test completed")