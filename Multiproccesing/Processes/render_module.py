import time
import cv2

from .process_module import ProcessModule
from Utils.timer import Timer


class RenderProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 120,
                    }
        
        self.get_parameters()

        self.timer = Timer('read_frame')


    def get_parametrs(self):
        self.fps = self.local_controls_parameters['fps']
        self.delta = self.local_controls_parameters['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
        while not self.should_stop():
            data_frame = self.queue_manager.input_render.get()
            
            id_memory = data_frame['id_memory']
            #print(f'processing_module: {id_memory}')

            frames = self.queue_manager.memory_manager.read_images("process_data", id_memory)
            timer_start = data_frame['time']

            elapsed = time.time() - timer_start
            #print(f"Таймер  {elapsed * 1000} мс")

            if len(frames) > 0:
                # Отображаем изображение
                cv2.imshow('Image', frames[0])
                cv2.waitKey(1)  # Ждем нажатия любой клавиши
            else:
                print("Не удалось загрузить изображение.")
            
            #self.queue_manager.input_capture.put(id_memory)
                
            #queue_manager.input_render.put(id_memory)
        
        cv2.destroyAllWindows()
        print(f'processing_module: STOP')


def main(queue_manager=None):
    process = RenderProcess(name='Render_process', 
                                queue_manager=queue_manager, 
                                control_queue=None)
    process.run()