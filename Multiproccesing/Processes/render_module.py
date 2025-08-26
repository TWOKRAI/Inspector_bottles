import time

from .process_module import ProcessModule
from Utils.timer import Timer

from Camera_module.frame_fps import FrameFPS


class RenderProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 120,
                    }
        
        self.get_parameters()

        self.fps_counter = FrameFPS(update_interval=1.0)

        self.timer_process = Timer('time_process_render')
        self.timer = Timer('read_frame')


    def get_parametrs(self):
        self.fps = self.local_controls_parameters['fps']
        self.delta = self.local_controls_parameters['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
        import cv2

        i = 0
        data_frame = None

        level_max = 300
        level_normal = 330
        level_min = 360

        while not self.should_stop():
            d = 0

            all_data = {}

            while not self.should_stop():
                data = self.queue_manager.input_render.get()
                d += 1

                all_data[data['name_process']] = data

                print(data['name_process'])

                if len(all_data) == 5:
                    break
                    
            print('собрал')

            self.timer_process.start()

            data_frame = all_data.pop('proc_processing')
            timer_start = data_frame['time']

            time_input_data = self.timer_process.start_time
            time_send_data = data_frame['time_send']
            
            id_memory = data_frame['id_memory']
            #print(f'processing_module: {id_memory}')

            frames = self.queue_manager.memory_manager.read_images("process_data", id_memory)
            frame = frames[0]
            
            #print(all_data)

            for _, data_crop in all_data.items():
                lines_cap = data_crop["lines_cap"]
                cap_pos = data_crop["cap_pos"]
                
                lines_level = data_crop["lines_level"]
                level_pos = data_crop["level_pos"]

                for line in lines_cap:
                    x1, y1, x2, y2 = line
                    x1 = x1 + cap_pos[0]
                    y1 = y1 + cap_pos[1]
                    x2 = x2 + cap_pos[0]
                    y2 = y2 + cap_pos[1]

                    cv2.line(frame, (x1, y1), (x2, y2), (120, 0, 180), 3) 

                if len(lines_level) > 0:
                    lines_level.sort(key=lambda line: line[1]) 

                    top_line = lines_level[0]
                    x1, y1, x2, y2 = top_line

                    # Корректируем координаты
                    x1 = x1 + level_pos[0] - 100
                    y1 = y1 + level_pos[1]
                    x2 = x2 + level_pos[0] + 100
                    y2 = y2 + level_pos[1]

                    y_middle = (y1+y2) / 2

                    if y_middle > level_min or y_middle < level_max:
                        color = (0, 0, 255)
                    else:
                        color = (255, 0, 0)
                    
                    cv2.line(frame, (x1, y1), (x2, y2), color, 6)  # Синий в BGR

                #timer_start = data_frame['time']

                #print(f"Таймер  {elapsed * 1000} мс")

                i += 1

                if len(frames) > 0:
                    # Отображаем изображение
                    cv2.imshow('Image', frame)
                    cv2.waitKey(1)  # Ждем нажатия любой клавиши
                else:
                    print("Не удалось загрузить изображение.")
                
                self.queue_manager.input_capture.put(id_memory)

                #self.queue_manager.input_render.put(id_memory)

                real_time = time.time()
                elapsed = time.time() - timer_start
                elapsed = elapsed * 1000
                data_cycle = [real_time, elapsed]

                self.fps  = self.fps_counter.update()

                if self.fps  > 0:
                    print(self.fps)

                self.timer_process.get_data()
                time_send = self.timer_process.real_time
                data = {'process_render': self.timer_process.result,
                        'time_input_render': [time_send, abs(time_input_data - time_send_data) * 1000],
                        'time_cycle': data_cycle,
                        'fps_render': [time.time(), self.fps]
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


def main(queue_manager=None, control_queue=None):
    process = RenderProcess(name='Render_process', 
                                queue_manager=queue_manager, 
                                control_queue=control_queue)
    process.run()