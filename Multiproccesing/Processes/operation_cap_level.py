import time

from .process_module import ProcessModule
from Utils.timer import Timer

from Create_bottles.preobrazovanie import detect_horizontal_lines


class CapLevelProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None, input_queue=None, num=1):
        super().__init__(name, queue_manager, control_queue)

        self.num = num 
        self.input_queue = input_queue

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 10,
                    }

        self.get_parameters()

        self.timer_process = Timer('time_process_processing')
        self.timer = Timer('read_frame')


    def get_parametrs(self):
        pass


    def main(self):
        import cv2
        import numpy as np

        while True:
            data_frame_crop = self.input_queue.get()
            
            self.timer_process.start()

            time_input_data = self.timer_process.start_time 
            time_send_data = data_frame_crop['time_send']
            
            id_memory = data_frame_crop['id_memory']
            #print(f'processing_module: {id_memory}')

            frames_cap = self.queue_manager.memory_manager.read_images(f"process_data_cap_{self.num}", id_memory)
            frames_level = self.queue_manager.memory_manager.read_images(f"process_data_level_{self.num}", id_memory)
            

            #cv2.imwrite('test.jpg', image_with_rect_2)

            #image_equ = cv2.equalizeHist(image_crop_level)

            frame_cap = frames_cap[0]

            # 2. Гауссово размытие для уменьшения шума
            image_blurred = cv2.GaussianBlur(frame_cap, (3, 3), 0)

            # Обнаружение линий с визуализацией этапов
            lines_level, all_images = detect_horizontal_lines(
                image_blurred,
                canny_threshold1=15,
                canny_threshold2=20,
                theta=np.pi/180,
                hough_threshold=50,
                min_line_length=100,
                max_line_gap=50,
                angle_tolerance=3,
                morph_size=0,
            )

            if len(lines_level) > 0:
                lines_level.sort(key=lambda line: line[1]) 

            data_frame_crop['lines_level'] = lines_level

            frame_level = frames_level[0]

            # Обнаружение линий с визуализацией этапов
            lines_cap, all_images = detect_horizontal_lines(
                frame_level,
                canny_threshold1=70,
                canny_threshold2=30,
                theta=np.pi/360,
                hough_threshold=70,
                min_line_length=10,
                max_line_gap=50,
                angle_tolerance=30,
                morph_size=2,
            )

            data_frame_crop['lines_cap'] = lines_cap

            data_frame_crop['name_process'] = f'proc_crop_{self.num}'

            time_send = time.time()
            data = {f'process_cap_level_{self.num}': self.timer_process.get_data(),
                    f'time_input_cap_level_{self.num}': [time_send, abs(time_input_data - time_send_data) * 1000]}
            self.queue_manager.input_graph.put(data)

            data_frame_crop['time_send'] = time.time()
            self.queue_manager.input_render.put(data_frame_crop)


def main(queue_manager=None, control_queue=None, input_queue=None, num=1):
    process = CapLevelProcess(name='Operation_process', 
                                queue_manager=queue_manager, 
                                control_queue=control_queue,
                                input_queue=input_queue,
                                num=num
                                )
    process.run()