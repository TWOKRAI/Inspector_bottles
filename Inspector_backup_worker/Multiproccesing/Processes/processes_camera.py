import threading
import cv2
import time
from queue import Empty
import logging

from Devices.Camera.camera_rtsp import Camera_rtsp
from Utils.timer import Timer
from Process_image.frame_detection import FrameDetection

class RTSPStreamProcessor:
    def __init__(self, queue_manager, name, rtsp_url):
        self.name = name
        
        self.queue_manager = queue_manager

        self.stop_proccess = False

        self.rtsp_url = rtsp_url

        self.camera = Camera_rtsp(rtsp_url)

        self.recording = False
        self.frame_counter = 1
        self.frame_interval = 1
        self.control_camera = {}

        self.index_memory = [0] * 12

        # Настройка логирования
        logging.basicConfig(filename='camera.log', level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s, ', encoding='utf-8')

        # Очистка лог-файла
        with open('camera.log', 'w'):
            pass

        self.control_thread = threading.Thread(target=self.control_update_thread)
        self.main_thread = threading.Thread(target=self.process_stream)
        self.memory_thread = threading.Thread(target=self.memory_delete_thread)

        self.init_control()

        print('Процесс RTSPStreamProcessor запущен')
        queue_manager.download.put(('read_rtsp_stream', True))


    def start(self):
        self.main_thread.start()
        self.control_thread.start()
        self.memory_thread.start()


    def stop(self):
        self.stop_proccess - True

        self.main_thread.join()
        self.control_thread.join()
        self.memory_thread.join()

        self.camera.release()

        print('Процесс RTSPStreamProcessor остановлен')


    def calculate_frame_interval(self, desired_fps):
        if desired_fps == 0:
            return 1 
        return max(1, round(self.camera.fps / desired_fps))
    

    def calculate_time_interval(self, desired_fps):
        if desired_fps == 0:
            return 1 
        return round(1 / desired_fps, 2)


    def get_control(self):
        self.enable_process = self.control_camera.get('enable_camera', True)
        self.record_video = self.control_camera.get('record_video', False)
        self.desired_fps = self.control_camera.get('fps', 20)

        #print('enable_camera', self.enable_process, 'record_video', self.record_video, 'fps', self.desired_fps)

        #self.frame_interval = self.calculate_frame_interval(self.desired_fps)
        self.frame_interval = self.calculate_time_interval(self.desired_fps) - 1/self.camera.fps * 0.7
        print('self.frame_interval', self.frame_interval)


    def init_control(self):
        try:
            self.control_camera = self.queue_manager.control_camera.get(timeout=1)
        except Empty:
            pass
        
        self.get_control()


    def control_update_thread(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            #self.queue_manager.control_camera_event.wait() 
            self.control_camera = self.queue_manager.control_camera.get()
            #self.queue_manager.control_camera_event.clear() 

            self.get_control()


    def memory_delete_thread(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            # try:
            #     id_memory_delete = self.queue_manager.memory_release_queue.get_nowait()
            # except Empty:
            #     time.sleep(0.005)
            #     continue

            id_memory_delete = self.queue_manager.memory_release_queue.get()
            
            #print('id_memory_delete', id_memory_delete)
            
            #self.queue_manager.memory_manager.release_memory("camera_data", id_memory_delete)
            #self.queue_manager.memory_manager.release_memory("process_data", id_memory_delete)
            #self.queue_manager.memory_manager.release_memory("neuroun_data", id_memory_delete)
            #self.queue_manager.memory_manager.release_memory("display_data", id_memory_delete)
            self.index_memory[id_memory_delete] = 0
            

    def process_stream(self):
        self.camera.clear_cache(10)

        one = False

        frame_counter = 1
        frame_id = 0

        timestamp_prev = 0
        timestamp_prev_2 = 0
                    
        timer = Timer('CADR GRAB')
        block = False
        id_memory_delete_save = 0

        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            #timer.start()

            if self.enable_process:
                if self.record_video and not self.recording:
                    self.camera.start_recording('output.avi', fps=self.desired_fps * 2)
                    self.recording = True
                elif not self.record_video and self.recording:
                    self.camera.stop_recording()
                    self.recording = False

                #self.camera.clear_cache(1)

                self.camera.create_cap()

                if not self.recording:
                    frame = self.camera.capture_frame()
                else:
                    frame = self.camera.record_frame()

                if frame is None:
                    self.camera = Camera_rtsp(self.rtsp_url)
                    logging.info(f'Переподключение к камере')
                    self.camera.clear_cache(20)
                    frame_counter = 1

                    continue
            else:
                #frame = self.camera.create_image_with_text((0, 0, 0), 'NO IMAGE', (255, 255, 255), 52)
                frame = FrameDetection.create_image_with_text(1280, 720, (0, 0, 0), 'NO IMAGE', (255, 255, 255), 52)

                self.camera.release()

            #timer.elapsed_time(print_log=True)

            #timer.start()
            timestamp = time.time()

            #if frame_counter % self.frame_interval == 0 and self.queue_manager.ready_app.is_set():
            if abs(timestamp - timestamp_prev) >= self.frame_interval and self.queue_manager.ready_app.is_set():
                # Находим свободный индекс
                #id_memory = self.queue_manager.memory_manager.find_free_index("camera_data")
                #logging.info(f'Кадр {timestamp}')

                for i in range(len(self.index_memory)):
                    if self.index_memory[i] == 0:
                        #print(f"Found free index: {i}")
                        id_memory = i
                        break
                    else:
                        id_memory = None
            
                if id_memory is not None:
                    if id_memory > 7:
                        self.queue_manager.clear_all_queue()
                        self.queue_manager.clear_all_event()
                        self.camera.clear_cache(20)

                        logging.info(f'CLEAR')

                        for i in range(len(self.index_memory)):
                            self.index_memory[i] = 0
                        
                        continue
                    #print(f"Writing to index {id_memory}")

                    # print("Тип данных изображения:", frame.dtype)  # Должно быть np.uint8 или np.uint32
                    # print("Размерность изображения:", frame.shape) # Формат (height, width, channels)


                        #timestamp_prev = timestamp
                        #self.camera.clear_cache(1)
                        #frame = self.camera.capture_frame()

                
                    #logging.info(f'Снятие кадра {timestamp}')

                    frame_id += 1

                    #frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)

                    frames = [frame]

                    self.index_memory[id_memory] = 1
                    self.queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)

                    data_frame = {
                        'id_memory': id_memory,
                        'current_time': timestamp,
                        'frame_counter': frame_counter,
                        'frame_id':  frame_id,
                    }

                    self.queue_manager.remove_old_frame_if_full(self.queue_manager.frame_processor_queue)
                    self.queue_manager.frame_processor_queue.put(data_frame)

                    #timer.elapsed_time(print_log=True)
                    
                    #self.queue_manager.frame_event.set()

                    # if id_memory > 5 and not block:
                    #     id_memory_delete_save = frame_id
                    #     print('id_memory_delete_save', id_memory_delete_save)
                    #     block = True

                    # if abs(frame_id - id_memory_delete_save) > 7 and block:
                    #     block = False
                    #print(f'Кадр {timestamp}')

                    # #timer.start()
                
                    # for _ in range(12):
                    #     try:
                    #         #id_memory_delete = self.queue_manager.memory_release_queue.get(timeout=0.0)
                    #         id_memory_delete = self.queue_manager.memory_release_queue.get_nowait()
                    #         print('id_memory_delete', id_memory_delete)
                            
                    #         #self.queue_manager.memory_manager.release_memory("camera_data", id_memory_delete)
                    #         #self.queue_manager.memory_manager.release_memory("process_data", id_memory_delete)
                    #         self.queue_manager.memory_manager.release_memory("neuroun_data", id_memory_delete)
                    #         #self.queue_manager.memory_manager.release_memory("display_data", id_memory_delete)
                    #         self.index_memory[id_memory_delete] = 0


                    #             # for i in range(12):
                    #             #     id_memory_delete = min(1, i)
                    #             #     self.index_memory[id_memory_delete] = 0

                    #             # self.queue_manager.clear_queue(self.queue_manager.frame_processor_queue, 1)
                    #             # self.queue_manager.clear_queue(self.queue_manager.neuroun_queue, 1)
                    #             # self.queue_manager.clear_queue( self.queue_manager.neural_output_queue, 1)
                    #             # self.queue_manager.clear_queue(self.queue_manager.robot_queue, 1)
                    #             # self.queue_manager.clear_queue( self.queue_manager.draw_queue, 1)
                    #             # self.queue_manager.clear_queue(self.queue_manager.display_queue, 1)

                    #     except Empty:
                    #         #print("Очередь пуста")
                    #         break

                    
                    #timer.elapsed_time(print_log=True)

                    # if not one:
                    #     time.sleep(0.5)
                    #     one = True

                else:
                    break
            
                timestamp_prev = timestamp
                frame = None

            
            
            # delta_time = abs(timestamp - timestamp_prev_2)
            # if delta_time > 0.1: 
                #timer.start()
                #self.camera.clear_cache(1)    
                #timer.elapsed_time(print_log=True)      
                #logging.info(f'Задержка {delta_time}')

            timestamp_prev_2  = timestamp

            #timer.start()
            #self.camera.clear_cache(1)
            #timer.elapsed_time(print_log=True) 

            frame_counter += 1

            if frame_counter > self.camera.fps:
                frame_counter = 1

            
            if frame_id > 120:
                frame_id = 0

            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.queue_manager.stop_event.set()
                break
                #pass

def camera_process(queue_manager, name):
    camera = RTSPStreamProcessor(
        queue_manager, 
        name = name, 
        rtsp_url = 'rtsp://admin:innotech@@192.168.1.64:554/live?transport=tcp',
    )
    
    camera.start()