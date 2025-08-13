import time
import cv2

from .process_module import ProcessModule
from color_process import ColorDetector
from Utils.timer import Timer


class Operation_process(ProcessModule):
    def __init__(self, queue_manager):
        super().__init__(queue_manager)

        self.local_controls_parametrs = {
                    'fps': 50, 
                    'delta': 120,
                    }

        self.timer = Timer('read_frame')


    def get_parametrs(self):
        self.fps = self.local_controls_parametrs['fps']
        self.delta = self.local_controls_parametrs['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
        self.detector = ColorDetector()

        while not self.should_stop():
            data_frame = self.queue_manager.input_processing.get()
            
            id_memory = data_frame['id_memory']
            #print(f'processing_module: {id_memory}')

            frames = self.queue_manager.memory_manager.read_images("camera_data", id_memory)

            self.detector.get_trackbar_values()

            param = {'fps': self.detector.fps}
            self.queue_manager.remove_old_if_full(self.queue_manager.control_capture)
            self.queue_manager.control_capture.put(param)

            # Обработка кадра
            processed_frame, mask = self.detector.process_frame(frames[0])

            frames = [processed_frame]
            
            self.queue_manager.memory_manager.write_images(frames, "process_data", id_memory)
            self.queue_manager.input_render.put(data_frame)

            # Отображение результатов
            cv2.imshow('Mask', mask)
            cv2.waitKey(1)
        
        cv2.destroyAllWindows()


def main(queue_manager=None):
    capture = Operation_process(queue_manager)
    capture.run()