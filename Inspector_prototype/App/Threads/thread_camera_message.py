from PyQt5.QtCore import QThread, pyqtSignal
from queue import Empty
import time


class CameraMessageThread(QThread):
    """Поток для получения сообщений от процесса камеры"""
    message_received = pyqtSignal(dict)
    
    def __init__(self, queue_manager, stop_event):
        super().__init__()
        self.queue_manager = queue_manager
        self.stop_event = stop_event
        self.running = True
    
    def run(self):
        """Основной цикл потока"""
        while self.running and not self.stop_event.is_set():
            try:
                # Блокирующее ожидание сообщения с таймаутом (читаем из отдельной очереди для App)
                message = self.queue_manager.camera_to_app.get(timeout=1)
                if message:
                    print(f"App CameraMessageThread: received message: {message.get('type')}")
                    self.message_received.emit(message)
            except Empty:
                # Таймаут - продолжаем цикл
                continue
            except Exception as e:
                print(f"Error in camera message thread: {e}")
                import traceback
                traceback.print_exc()
                break
    
    def stop(self):
        """Остановить поток"""
        self.running = False
        self.wait(2000)  # Ждем до 2 секунд для завершения
