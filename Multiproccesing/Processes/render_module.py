import time

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

        self.timer_process = Timer('time_process_render')
        self.timer = Timer('read_frame')


    def get_parametrs(self):
        self.fps = self.local_controls_parameters['fps']
        self.delta = self.local_controls_parameters['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
        import cv2

        i = 0
        while not self.should_stop():
            data_frame = self.queue_manager.input_render.get()
            self.timer_process.start()

            time_input_data = self.timer_process.start_time
            time_send_data = data_frame['time_send']
            
            id_memory = data_frame['id_memory']
            #print(f'processing_module: {id_memory}')

            frames = self.queue_manager.memory_manager.read_images("process_data", id_memory)
            timer_start = data_frame['time']

            #print(f"Таймер  {elapsed * 1000} мс")

            i += 1

            if len(frames) > 0:
                # Отображаем изображение
                cv2.imshow('Image', frames[0])
                cv2.waitKey(1)  # Ждем нажатия любой клавиши
            else:
                print("Не удалось загрузить изображение.")
            
            #self.queue_manager.input_capture.put(id_memory)

            #queue_manager.input_render.put(id_memory)

            real_time = time.time()
            elapsed = time.time() - timer_start
            elapsed = elapsed * 1000
            data_cycle = [real_time, elapsed]

            self.timer_process.get_data()
            time_send = self.timer_process.real_time
            data = {'process_render': self.timer_process.result,
                    'time_input_render': [time_send, abs(time_input_data - time_send_data) * 1000],
                    'time_cycle': data_cycle
                    }
            self.queue_manager.input_graph.put(data)
            
            # real_time = time.time()
            # elapsed = time.time() - timer_start
            # elapsed = elapsed * 1000

            # data_cycle = [real_time, elapsed]
            # data = {'time_cycle': data_cycle}
            # self.queue_manager.input_graph_cycle.put(data)

        cv2.destroyAllWindows()
        print(f'processing_module: STOP')


def main(queue_manager=None):
    process = RenderProcess(name='Render_process', 
                                queue_manager=queue_manager, 
                                control_queue=None)
    process.run()