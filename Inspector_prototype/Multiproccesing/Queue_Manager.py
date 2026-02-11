from multiprocessing import Queue, Event
from queue import Empty
import numpy as np

from Multiproccesing.Memory_Manager import ImageMemoryManager


class QueueManager:
    def __init__(self):
        self.stop_event = Event()
        self.ready_app = Event()

        self.buffer_size = 30

        # Очереди для передачи данных между процессами
        self.frame_processor_queue = Queue(maxsize=self.buffer_size)  # Кадры от камеры к обработке
        self.display_queue = Queue(maxsize=self.buffer_size)  # Обработанные кадры к UI
        self.memory_release_queue = Queue(maxsize=12)  # Освобождение памяти

        # Очереди управления
        self.control_processing = Queue(maxsize=1)  # Управление процессом обработки (из App/UI)
        self.ui_to_camera = Queue(maxsize=10)  # Управление камерой (из UI SDK)
        self.camera_to_ui = Queue(maxsize=10)  # Ответы от камеры к UI SDK
        self.control_ui = Queue(maxsize=1)  # Управление видимостью UI SDK окна

        # События
        self.control_camera_event = Event()
        self.control_processing_event = Event()

        # Менеджер памяти
        self.memory_manager = ImageMemoryManager()
        
        # Конфигурация разделяемой памяти для прототипа
        memory_names = {
            'camera_data': (1, (720, 1280, 3), np.uint8),  # Кадры с камеры
            'process_data': (1, (720, 1280, 3), np.uint8),  # Обработанные кадры
            'display_data': (1, (720, 1280, 3), np.uint8),  # Кадры для отображения в App
        }
        
        coll = 12  # количество блоков памяти

        # Создаем разделяемую память
        self.memory_manager.create_memory_dict(memory_names, coll)

        self.total_modules = 0

    def clear_queue(self, queue, keep_elements=0):
        """Очистить очередь, оставив указанное количество элементов"""
        while queue.qsize() > keep_elements:
            try:
                queue.get_nowait()
            except Empty:
                continue

    def remove_old_frame_if_full(self, queue):
        """Удалить старые данные, если очередь заполнена"""
        if queue.full():
            try:
                queue.get_nowait()
            except Empty:
                pass

    def get_queue_sizes(self):
        """Получить размеры всех очередей"""
        sizes = {}
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, Queue):
                sizes[attr_name] = attr.qsize()
        return sizes

    def clear_all_queue(self):
        """Очистить все очереди"""
        print('Очистка всех очередей')
        
        self.clear_queue(self.frame_processor_queue, 0)
        self.clear_queue(self.display_queue, 0)
        self.clear_queue(self.control_processing, 0)
        self.clear_queue(self.ui_to_camera, 0)
        self.clear_queue(self.camera_to_ui, 0)
        self.clear_queue(self.control_ui, 0)
        self.clear_queue(self.memory_release_queue, 0)

    def clear_all_event(self):
        """Сбросить все события"""
        self.control_camera_event.clear()
        self.control_processing_event.clear()
