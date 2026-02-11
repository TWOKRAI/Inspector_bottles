from PyQt5.QtCore import QThread, pyqtSignal
from queue import Empty
import time

from App.Windows.message_window import MessageWindow


class BotThread(QThread):
    message = pyqtSignal(tuple)

    def __init__(self, window_manager):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen


    def run(self):
        while not self.stop_event.is_set():
            try:
                #bot_message = self.queue_manager.bot_message.get(timeout=0.1)
                bot_message = self.queue_manager.bot_message.get_nowait()
            except Empty:
                time.sleep(0.1)
                continue
            
            if isinstance(bot_message, tuple):
                self.message.emit(bot_message)