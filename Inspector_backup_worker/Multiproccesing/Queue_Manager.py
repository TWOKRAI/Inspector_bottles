from multiprocessing import Queue, Event
from queue import Empty
import numpy as np

from Multiproccesing.Memory_Manager import ImageMemoryManager


class QueueManager:
    def __init__(self):
        self.stop_event = Event()
        self.ready_app = Event()
        self.robot_on = Event()

        self.buffer_size = 30

        self.frame_queue_processor = Queue(maxsize=self.buffer_size)
        self.result_queue = Queue()

        self.memory_release_queue = Queue(maxsize=12)
        self.frame_processor_queue = Queue(maxsize=self.buffer_size)

        self.neuroun_queue = Queue(maxsize=self.buffer_size)
        self.neural_output_queue = Queue(maxsize=self.buffer_size)
        self.robot_queue = Queue(maxsize=self.buffer_size)
        self.draw_queue = Queue(maxsize=self.buffer_size)
        self.display_queue = Queue(maxsize=self.buffer_size)


        self.result_frame_queue = Queue(maxsize=1)
        self.confirmation_queue = Queue(maxsize=1)

        self.input_draw_queue = Queue(maxsize=self.buffer_size)
        self.output_draw_queue = Queue(maxsize=self.buffer_size)

        self.control_frame_process = Queue(maxsize=1)
        self.control_neuroun = Queue(maxsize=1)
        self.control_camera = Queue(maxsize=1)
        self.control_camera_out = Queue(maxsize=1)
        self.control_robot = Queue(maxsize=1)
        self.control_conveyor = Queue(maxsize=1)
        self.control_draw = Queue(maxsize=1)

        self.download = Queue()

        self.bot_message = Queue()
        self.bot_message_send = Queue()

        self.reset_count = Event()

        self.neuroun_event = Event()
        self.neural_output_event = Event()
        self.robot_event = Event()
        self.draw_event = Event()
        self.display_event = Event()
        self.frame_event = Event()

        self.result_frame_event = Event()
        self.confirmation_event = Event()

        self.input_draw_event = Event()
        self.output_draw_event = Event()

        self.control_frame_process_event = Event()
        self.control_neuroun_event = Event()
        self.control_camera_out_event = Event()
        self.control_camera_event = Event()
        self.control_robot_event = Event()
        self.control_conveyor_event = Event()
        self.control_draw_event = Event()


        self.memory_manager = ImageMemoryManager()
        
        memory_names = {
            'camera_data': (1, (720, 1280, 3), np.uint8),
            'camera_data_out': (1, (720, 1280, 3), np.uint8),
            'process_data': (6, (720, 1280, 3), np.uint8), 
            'neuroun_data': (21, (72, 72, 3), np.uint8),
            'display_data': (1, (720, 1280, 3), np.uint8),
        }
        
        coll = 12  # количество блоков памяти

        # Создаем разделяемую память
        self.memory_manager.create_memory_dict(memory_names, coll)

        # size = self.memory_manager.calculate_memory_for_images(1, (1280, 720, 3))
        # self.memory_manager.create_memory(f'camera_frame', size*2, self.buffer_size)
        
        # size = self.memory_manager.calculate_memory_for_images(7, (1280, 720, 3))
        # self.memory_manager.create_memory(f'process_frames', size*2, self.buffer_size)
        
        # # self.memory_manager.create_memory('camera_frame', size*2)

        # # self.memory_objects_camera = [
        # #     self.memory_manager.create_memory(f'camera_frame_{i}', size*2)
        # #     for i in range(12)
        # # ]
        
        # size = self.memory_manager.calculate_memory_for_images(21, (72, 72, 3))
        # self.memory_manager.create_memory(f'neuroun_frames', size*2, self.buffer_size)


        # size = self.memory_manager.calculate_memory_for_images(1, (1280, 720, 3))
        # self.memory_manager.create_memory(f'display_frames', size*2, self.buffer_size)

        # # self.memory_objects_neuroun = [
        # #     self.memory_manager.create_memory(f'neuroun_frames_{i}', size*2)
        # #     for i in range(12)
        # # ]

        #print(self.memory_manager.memories)

        self.total_modules = 0


    def clear_queue(self, queue, keep_elements=0):
        while queue.qsize() > keep_elements:
            try:
                queue.get_nowait()
            except Empty:
                continue


    def remove_old_frame_if_full(self, queue):
        if queue.full():
            try:
                queue.get_nowait()
            except Empty:
                pass


    def get_queue_sizes(self):
        sizes = {}
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, Queue):
                sizes[attr_name] = attr.qsize()
        return sizes


    def clear_all_queue(self):
        print('очистка очереди')
        
        self.clear_queue(self.frame_processor_queue, 0)
        self.clear_queue(self.neuroun_queue, 0)
        self.clear_queue(self.neural_output_queue, 0)
        self.clear_queue(self.robot_queue, 0)
        self.clear_queue(self.draw_queue, 0)
        self.clear_queue(self.display_queue, 0)

        self.clear_queue(self.control_frame_process, 0)
        self.clear_queue(self.control_neuroun, 0)
        self.clear_queue(self.control_camera, 0)
        self.clear_queue(self.control_camera_out, 0)
        self.clear_queue(self.control_robot, 0)
        self.clear_queue(self.control_conveyor, 0)
        self.clear_queue(self.control_draw, 0)
        
        self.clear_queue(self.bot_message, 0)
        self.clear_queue(self.bot_message_send, 0)

        #self.clear_queue(self.download, 0)

        self.neuroun_queue.put('clear_session')
        self.clear_all_queue


    def clear_all_event(self):
        self.neuroun_event.clear()
        self.neural_output_event.clear()
        self.robot_event.clear()
        self.draw_event.clear()
        self.display_event.clear()
        self.frame_event.clear()

        self.result_frame_event.clear()
        self.confirmation_event.clear()

        self.input_draw_event.clear()
        self.output_draw_event.clear()

        self.control_frame_process_event.clear()
        self.control_neuroun_event.clear()
        self.control_camera_event.clear()
        self.control_camera_out_event.clear()
        self.control_robot_event.clear()
        self.control_conveyor_event.clear()
        self.control_draw_event.clear()
        
