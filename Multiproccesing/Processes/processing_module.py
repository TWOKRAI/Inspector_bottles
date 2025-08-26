import time

from .process_module import ProcessModule
from Utils.timer import Timer


class OperationProcess(ProcessModule):
    def __init__(self, name='Process', queue_manager=None, control_queue=None):
        super().__init__(name, queue_manager, control_queue)

        self.local_controls_parameters = {
                    'fps': 50, 
                    'delta': 10,
                    }

        self.get_parameters()

        self.timer_process = Timer('time_process_processing')
        self.timer = Timer('read_frame')


    def get_parametrs(self):
        self.fps = self.local_controls_parameters['fps']
        self.delta = self.local_controls_parameters['delta']
        
        print('self.fps', self.fps, 'self.delta', self.delta)


    def main(self):
        import cv2
        #from color_process import ColorDetector

        from Create_bottles.preobrazovanie import ObjectDetector, GrayConversionMethod, ThresholdMethod, MorphOperation, ContourFilterMethod

        # self.detector = ColorDetector()
        # self.detector.get_trackbar_values()

        detector1 = ObjectDetector(
            gray_conversion_method=GrayConversionMethod.LUMINANCE,
            threshold_method=ThresholdMethod.BINARY,
            morph_operations=[
                {"operation": MorphOperation.CLOSE, "kernel_size": 5},
                {"operation": MorphOperation.OPEN, "kernel_size": 5}
            ],
            contour_filter_method=ContourFilterMethod.AREA,
            threshold_params={"thresh": 190, 
                            "maxval": 255, 
                            "type": cv2.THRESH_BINARY_INV},
            filter_params={"min_area": 1000}
        )
        

        cap_crop = [(160, 33), (370, 190)]
        level_crop = [(180, 230), (350, 700)]

        while not self.should_stop():
            data_frame = self.queue_manager.input_processing.get()
            self.timer_process.start()
            
            time_input_data = self.timer_process.start_time 
            time_send_data = data_frame['time_send']
            
            id_memory = data_frame['id_memory']
            #print(f'processing_module: {id_memory}')

            frames = self.queue_manager.memory_manager.read_images("camera_data", id_memory)

            frame = frames[0]
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            image_frame = frame_gray[:300, :]
            
            # Обнаруживаем объекты
            centers, contours = detector1.detect(image_frame, return_contours=True)
            
            #self.detector.get_trackbar_values()

            # Обработка кадра
            #processed_frame, mask = self.detector.process_frame(frames[0])
            
            list_crop_cap = []
            list_crop_level = []
            data_frame_crop = {}

            data_frame_crop['id_memory'] = id_memory

            i = 1
            for pos in centers:
                x, y = pos
                
                delta_x = abs(cap_crop[0][0] - cap_crop[1][0])
                cap_x1 = x - delta_x // 2
                cap_x2 = x + delta_x // 2
                cap_y1 = cap_crop[0][1]
                cap_y2 = cap_crop[1][1]

                # # Координаты прямоугольника (верхний левый и нижний правый углы)
                # cap_x1, cap_y1 = 160, 33 # верхний левый угол
                # cap_x2, cap_y2 = 370, 190  # нижний правый угол

                # cv2.line(image_with_rect, (x, 0), (x, image_with_rect.shape[1]), color=(0, 255, 255), thickness=7)

                # cv2.rectangle(image_with_rect, (cap_x1, cap_y1), (cap_x2, cap_y2), color=(0, 255, 255), thickness=3)

                image_crop_cap = frame_gray[cap_y1:cap_y2, cap_x1:cap_x2]

                delta_x = abs(level_crop[0][0] - level_crop[1][0])

                level_x1 = x - delta_x // 2
                level_x2 = x + delta_x // 2
                level_y1 = level_crop[0][1]
                level_y2 = level_crop[1][1]

                # # Координаты прямоугольника (верхний левый и нижний правый углы) 
                # level_x1, level_y1 = 180, 230  # верхний левый угол
                # level_x2, level_y2 = 350, 700  # нижний правый угол

                #cv2.rectangle(image_with_rect, (level_x1, level_y1), (level_x2, level_y2), color=(0, 0, 255), thickness=3)

                image_crop_level = frame_gray[level_y1:level_y2, level_x1:level_x2]

                # bottle_crop = {}
                # bottle_crop['cap_pos'] = (cap_x1, cap_y1)
                # bottle_crop['level_pos'] = (level_x1, level_y1)

                self.queue_manager.memory_manager.write_images([image_crop_cap], f"process_data_cap_{i}", id_memory)
                self.queue_manager.memory_manager.write_images([image_crop_level], f"process_data_level_{i}", id_memory)

                match i:
                    case 1:
                        data_frame_crop['cap_pos'] = (cap_x1, cap_y1)
                        data_frame_crop['level_pos'] = (level_x1, level_y1)
                        data_frame_crop['time_send'] = time.time()
                        
                        self.queue_manager.input_cap_level_1.put(data_frame_crop)
                    case 2:
                        data_frame_crop['cap_pos'] = (cap_x1, cap_y1)
                        data_frame_crop['level_pos'] = (level_x1, level_y1)
                        data_frame_crop['time_send'] = time.time()
                        
                        self.queue_manager.input_cap_level_2.put(data_frame_crop)
                    case 3:
                        data_frame_crop['cap_pos'] = (cap_x1, cap_y1)
                        data_frame_crop['level_pos'] = (level_x1, level_y1)
                        data_frame_crop['time_send'] = time.time()

                        self.queue_manager.input_cap_level_3.put(data_frame_crop)
                    case 4:
                        data_frame_crop['cap_pos'] = (cap_x1, cap_y1)
                        data_frame_crop['level_pos'] = (level_x1, level_y1)
                        data_frame_crop['time_send'] = time.time()
                        
                        self.queue_manager.input_cap_level_4.put(data_frame_crop)

                i += 1

            frames = [frame]
            self.queue_manager.memory_manager.write_images(frames, "process_data", id_memory)
            data_frame['time_send'] = time.time()
            data_frame['name_process'] = 'proc_processing'

            self.queue_manager.input_render.put(data_frame)

            # Отображение результатов
            #cv2.imshow('Mask', mask)
        
            # param = {'fps': self.detector.fps}
            # self.queue_manager.remove_old_if_full(self.queue_manager.control_capture)
            # self.queue_manager.control_capture.put(param)

            # param = {'min_x': self.detector.min_x,
            #          'max_x': self.detector.max_x,}
            
            #self.queue_manager.remove_old_if_full(self.queue_manager.control_graph)
            #self.queue_manager.control_graph.put(param)    

            #cv2.waitKey(1)

            time_send = time.time()
            data = {'process_processing': self.timer_process.get_data(),
                    'time_input_processing': [time_send, abs(time_input_data - time_send_data) * 1000]}
            self.queue_manager.input_graph.put(data)

        
       # cv2.destroyAllWindows()


def main(queue_manager=None, control_queue=None):
    process = OperationProcess(name='Operation_process', 
                                queue_manager=queue_manager, 
                                control_queue=control_queue)
    process.run()