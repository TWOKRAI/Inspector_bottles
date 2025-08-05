from multiprocessing import Queue, Event
from queue import Empty
import numpy as np

from .Memory_Manager import ImageMemoryManager


class QueueManager:
    def __init__(self):
        self.buffer_size = 30
        
        # Конфигурация всех очередей: {имя: размер_буфера}
        self.queues_config = {
            'control_ui': 1,
            'control_render': 1,
            'control_capture': 1,
            'control_processing': 1,
            'control_communication': 1,
            'input_render': self.buffer_size,
            'output_render': self.buffer_size,
            'input_capture': self.buffer_size,
            'output_capture': self.buffer_size,
            'input_processing': self.buffer_size,
            'output_processing': self.buffer_size,
            'input_communication': self.buffer_size,
            'output_communication': self.buffer_size,
        }
        
        # Конфигурация событий: [список имен]
        self.events_config = [
            'stop_event',
            'ready_app',
            'control_frame_process_event',
            'control_neuroun_event',
            'control_camera_event',
            'control_robot_event',
            'control_conveyor_event',
            'control_draw_event',
        ]
        
        # Создать очереди на основе конфигурации
        self.queues = {}
        for name, maxsize in self.queues_config.items():
            queue = Queue(maxsize=maxsize)
            setattr(self, name, queue)
            self.queues[name] = queue

        # Создать события на основе конфигурации
        self.events = {}
        for name in self.events_config:
            event = Event()
            setattr(self, name, event)
            self.events[name] = event

        # Менеджер памяти
        self.memory_manager = ImageMemoryManager()
        memory_names = {
            'camera_data': (1, (1080, 1920, 3), np.uint8),
            'camera_data_out': (1, (720, 1280, 3), np.uint8),
            'process_data': (6, (720, 1280, 3), np.uint8), 
            'neuroun_data': (21, (72, 72, 3), np.uint8),
            'display_data': (1, (720, 1280, 3), np.uint8),
        }
        self.memory_manager.create_memory_dict(memory_names, coll=12)
        self.total_modules = 0


    def clear_queue(self, queue, keep_elements=0):
        """Очистить очередь, оставив указанное количество элементов."""
        while queue.qsize() > keep_elements:
            try:
                queue.get_nowait()
            except Empty:
                continue


    def remove_old_if_full(self, queue):
        """Удалить старые данные, если очередь заполнена."""
        if queue.full():
            try:
                queue.get_nowait()
            except Empty:
                pass


    def get_queue_sizes(self):
        """Получить размеры всех очередей."""
        return {name: queue.qsize() for name, queue in self.queues.items()}


    def clear_all_queues(self):
        """Очистить все очереди."""
        for queue in self.queues.values():
            self.clear_queue(queue, keep_elements=0)

        print('Очистка всех очередей')


    def clear_all_events(self):
        """Сбросить все события."""
        for event in self.events.values():
            event.clear()
        
        print('Сброс всех событий')


if __name__ == '__main__':
    # Создание менеджера
    manager = QueueManager()

    # Добавление данных в очередь
    manager.input_render.put({"frame": np.zeros((720, 1280, 3)), "timestamp": 12345})

    # Проверка заполненности и удаление старого элемента
    if manager.output_capture.full():
        manager.remove_old_if_full(manager.output_capture)

    # Получение данных из очереди
    try:
        data = manager.input_processing.get(timeout=1.0)
        print(f"Получены данные: {data['timestamp']}")
    except Empty:
        print("Очередь пуста")

    # Очистка конкретной очереди
    manager.clear_queue(manager.control_ui)

    # Получение статистики по очередям
    sizes = manager.get_queue_sizes()
    print(f"Размер input_render: {sizes['input_render']}")

        # Установка события
    manager.ready_app.set()

    # Проверка события
    if manager.control_camera_event.is_set():
        print("Камера готова к работе")

    # Ожидание события с таймаутом
    if manager.stop_event.wait(timeout=5.0):
        print("Получен сигнал остановки")
    else:
        print("Таймаут ожидания")

    # Сброс события
    manager.control_frame_process_event.clear()

    # Очистка всех событий
    manager.clear_all_events()