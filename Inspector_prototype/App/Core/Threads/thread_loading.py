import time
from PyQt5.QtCore import  QThread, pyqtSignal
from queue import Empty


class Loading(QThread):
    progress_updated = pyqtSignal(int)  # Процент загрузки (0-100)
    window_close = pyqtSignal()

    def __init__(self, queue_manager, stop_event):
        super().__init__()
        self.queue_manager = queue_manager
        self.stop_event = stop_event

        self.ready_processes = set()  # Множество готовых процессов
        self.total_processes = 0

    def run(self):
        time.sleep(0.5)  # Небольшая задержка для инициализации

        # Если total_modules = 0, сразу закрываем окно загрузки
        if self.queue_manager.total_modules == 0:
            self.queue_manager.ready_app.set()
            self.window_close.emit()
            self.quit()
            print('Поток загрузки завершился (total_modules = 0)')
            return

        self.total_processes = self.queue_manager.total_modules
        print(f'Loading thread: ожидаем готовности {self.total_processes} процессов')

        while not self.stop_event.is_set():
            # Проверяем готовность всех процессов
            if len(self.ready_processes) >= self.total_processes:
                # Все процессы готовы
                self.progress_updated.emit(100)
                time.sleep(0.3)  # Небольшая задержка для отображения 100%
                self.queue_manager.ready_app.set()
                self.window_close.emit()
                print(f'Loading thread: все {self.total_processes} процессов готовы')
                break

            try:
                # Читаем сигнал готовности процесса из очереди
                process_name = self.queue_manager.process_ready_queue.get(timeout=0.5)
                if process_name and process_name not in self.ready_processes:
                    self.ready_processes.add(process_name)
                    # Вычисляем процент готовности
                    progress_percent = int((len(self.ready_processes) / self.total_processes) * 100)
                    self.progress_updated.emit(progress_percent)
                    print(f'Loading thread: процесс "{process_name}" готов ({len(self.ready_processes)}/{self.total_processes}, {progress_percent}%)')
            except Empty:
                continue
            except Exception as e:
                print(f"Error in loading thread: {e}")
                import traceback
                traceback.print_exc()
                break

        self.quit()
        print('Поток загрузки завершился')

