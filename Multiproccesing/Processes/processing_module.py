import time
import cv2

from .process_module import ProcessModule
from color_process import ColorDetector
from Utils.timer import Timer


class OperationProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 10,
                    }

        self.get_parameters()

        self.timer_process = Timer('time_process')
        self.timer = Timer('read_frame')


    def get_parametrs(self):
        self.fps = self.local_controls_parameters['fps']
        self.delta = self.local_controls_parameters['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
        self.detector = ColorDetector()

        while not self.should_stop():
            self.timer_process.start()

            data_frame = self.queue_manager.input_processing.get()
            
            id_memory = data_frame['id_memory']
            #print(f'processing_module: {id_memory}')

            frames = self.queue_manager.memory_manager.read_images("camera_data", id_memory)

            self.detector.get_trackbar_values()

            param = {'fps': self.detector.fps}
            self.queue_manager.remove_old_if_full(self.queue_manager.control_capture)
            self.queue_manager.control_capture.put(param)

            param = {'min_x': self.detector.min_x,
                     'max_x': self.detector.max_x,}
            self.queue_manager.remove_old_if_full(self.queue_manager.control_graph)
            self.queue_manager.control_graph.put(param)     

            # Обработка кадра
            processed_frame, mask = self.detector.process_frame(frames[0])

            frames = [processed_frame]
            
            self.queue_manager.memory_manager.write_images(frames, "process_data", id_memory)
            self.queue_manager.input_render.put(data_frame)

            # Отображение результатов
            cv2.imshow('Mask', mask)
            cv2.waitKey(1)

            data = {'process_processing': self.timer_process.get_data()}
            self.queue_manager.input_graph.put(data)
        
        cv2.destroyAllWindows()


def main(queue_manager=None):
    process = OperationProcess(name='Operation_process', 
                                queue_manager=queue_manager, 
                                control_queue=None)
    process.run()