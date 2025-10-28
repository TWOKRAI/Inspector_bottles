import time
from PyQt5.QtCore import QThread, pyqtSignal
from queue import Empty


class Loading(QThread):
    progress_updated = pyqtSignal(int)
    window_close = pyqtSignal()

    def __init__(self, queue_manager):
        super().__init__()
        self.queue_manager = queue_manager
        self.stop_event = queue_manager.stop_event

        self.download_data = []
        self.len_data = 0


    def run(self):
        try:
            while not self.stop_event.is_set():
                if self.len_data >= self.queue_manager.total_modules:
                    self.window_close.emit()
                    break

                try:
                    data = self.queue_manager.download.get(timeout=1)
                    self.download_data.append(data)
                    print(data)
                except Empty:
                    continue

                if len(self.download_data) >= self.len_data:
                    self.len_data += 1

                    self.progress_updated.emit(self.len_data)
                    time.sleep(0.25)

                if self.len_data >= self.queue_manager.total_modules:
                    time.sleep(1.5)

                    self.window_close.emit()
                    self.download_data = []
                    self.queue_manager.ready_app.set()
                    break
        finally:
            self.quit()

        print('Поток загрузки завершился')

