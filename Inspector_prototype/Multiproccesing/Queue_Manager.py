from multiprocessing import Queue, Event
from queue import Empty
import numpy as np

from .Memory_Manager import ImageMemoryManager


class QueueManager:
    def __init__(self):
        self.stop_event = Event()
        self.ready_app = Event()

        self.buffer_size = 30

        # Очереди для передачи данных между процессами
        self.frame_processor_queue = Queue(maxsize=self.buffer_size)  # Кадры от камеры к обработке
        self.display_queue = Queue(maxsize=self.buffer_size)  # Обработанные кадры к UI
        self.memory_release_queue = Queue(maxsize=12)  # Освобождение памяти
        self.frame_queue = Queue(maxsize=self.buffer_size)  # Кадры для UI SDK (временная очередь)

        # Очереди управления (для совместимости с App)
        self.control_processing = Queue(maxsize=1)  # Управление процессом обработки (из App/UI)
        self.control_frame_process = Queue(maxsize=1)  # Управление процессом обработки кадров (для App)
        self.control_camera = Queue(maxsize=1)  # Управление камерой (для App)
        self.control_conveyor = Queue(maxsize=1)  # Управление конвейером (для App)
        self.control_neuroun = Queue(maxsize=1)  # Управление нейросетью (для App)
        self.control_draw = Queue(maxsize=1)  # Управление отрисовкой (для App)
        self.control_robot = Queue(maxsize=1)  # Управление роботом (для App)
        
        # Очереди для UI SDK
        self.ui_to_camera = Queue(maxsize=10)  # Управление камерой (из UI SDK)
        self.camera_to_ui = Queue(maxsize=10)  # Ответы от камеры к UI SDK
        self.camera_to_app = Queue(maxsize=10)  # Ответы от камеры к App (отдельная очередь)
        self.control_ui = Queue(maxsize=1)  # Управление видимостью UI SDK окна

        # Очереди для бота и других сервисов (заглушки для совместимости)
        self.bot_message = Queue(maxsize=self.buffer_size)
        self.bot_message_send = Queue(maxsize=self.buffer_size)
        self.download = Queue()  # Очередь для загрузки/статусов
        self.process_ready_queue = Queue()  # Очередь для сигналов готовности процессов

        # События
        self.control_camera_event = Event()
        self.control_processing_event = Event()
        self.control_conveyor_event = Event()
        self.control_neuroun_event = Event()
        self.control_draw_event = Event()
        self.control_robot_event = Event()
        self.control_frame_process_event = Event()

        # Менеджер памяти
        self.memory_manager = ImageMemoryManager()
        
        # Конфигурация разделяемой памяти для прототипа
        memory_names = {
            'camera_data': (1, (720, 1280, 3), np.uint8),  # Кадры с камеры
            'camera_data_out': (1, (720, 1280, 3), np.uint8),  # Кадры с камеры (выходная, для App)
            'process_data': (6, (720, 1280, 3), np.uint8),  # Обработанные кадры (6 изображений)
            'neuroun_data': (21, (72, 72, 3), np.uint8),  # Данные для нейросети (21 изображение 72x72)
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
        self.clear_queue(self.frame_queue, 0)
        self.clear_queue(self.memory_release_queue, 0)
        
        # Очереди управления
        self.clear_queue(self.control_processing, 0)
        self.clear_queue(self.control_frame_process, 0)
        self.clear_queue(self.control_camera, 0)
        self.clear_queue(self.control_conveyor, 0)
        self.clear_queue(self.control_neuroun, 0)
        self.clear_queue(self.control_draw, 0)
        self.clear_queue(self.control_robot, 0)
        
        # UI SDK очереди
        self.clear_queue(self.ui_to_camera, 0)
        self.clear_queue(self.camera_to_ui, 0)
        self.clear_queue(self.control_ui, 0)
        
        # Другие очереди
        self.clear_queue(self.bot_message, 0)
        self.clear_queue(self.bot_message_send, 0)
        self.clear_queue(self.download, 0)

    def clear_all_event(self):
        """Сбросить все события"""
        self.control_camera_event.clear()
        self.control_processing_event.clear()
        self.control_conveyor_event.clear()
        self.control_neuroun_event.clear()
        self.control_draw_event.clear()
        self.control_robot_event.clear()
        self.control_frame_process_event.clear()
