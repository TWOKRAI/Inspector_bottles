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

        # # Настройка логирования
        # logging.basicConfig(filename='camera.log', level=logging.INFO,
        #                     format='%(asctime)s - %(levelname)s - %(message)s, ', encoding='utf-8')

        # # Очистка лог-файла
        # with open('camera.log', 'w'):
        #     pass

        self.control_thread = threading.Thread(target=self.control_update_thread)
        self.main_thread = threading.Thread(target=self.process_stream)
        #self.memory_thread = threading.Thread(target=self.memory_delete_thread)

        self.init_control()

        print('Процесс RTSPStreamProcessor запущен')
        queue_manager.download.put(('read_rtsp_stream', True))


    def start(self):
        self.main_thread.start()
        self.control_thread.start()
        #self.memory_thread.start()


    def stop(self):
        self.stop_proccess - True

        self.main_thread.join()
        self.control_thread.join()
        # self.memory_thread.join()

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
        self.enable_process = self.control_camera.get('enable_camera_out', True)
        self.record_video = self.control_camera.get('record_video', False)
        self.desired_fps = self.control_camera.get('fps', 20)

        #print('enable_camera', self.enable_process, 'record_video', self.record_video, 'fps', self.desired_fps)

        #self.frame_interval = self.calculate_frame_interval(self.desired_fps)
        self.frame_interval = self.calculate_time_interval(self.desired_fps) - 1/self.camera.fps * 0.7
        print('self.frame_interval_out_camera', self.frame_interval)


    def init_control(self):
        try:
            self.control_camera = self.queue_manager.control_camera_out.get(timeout=1)
        except Empty:
            pass
        
        self.get_control()


    def control_update_thread(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            #self.queue_manager.control_camera_out_event.wait() 
            self.control_camera = self.queue_manager.control_camera_out.get()
            #self.queue_manager.control_camera_out_event.clear() 

            self.get_control()


    # def memory_delete_thread(self):
    #     while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
    #         try:
    #             #self.control_camera = self.queue_manager.control_camera.get(timeout=1)
    #             id_memory_delete = self.queue_manager.memory_release_queue.get_nowait()
    #         except Empty:
    #             time.sleep(0.05)
    #             continue
            
    #         #print('id_memory_delete', id_memory_delete)
            
    #         self.queue_manager.memory_manager.release_memory("camera_data", id_memory_delete)
    #         self.queue_manager.memory_manager.release_memory("process_data", id_memory_delete)
    #         self.queue_manager.memory_manager.release_memory("neuroun_data", id_memory_delete)
    #         self.queue_manager.memory_manager.release_memory("display_data", id_memory_delete)
    #         self.index_memory[id_memory_delete] = 0
            

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
            if self.enable_process:
                if self.record_video and not self.recording:
                    self.camera.start_recording('output.avi')
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
                self.camera.release()

                frame = FrameDetection.create_image_with_text(1280, 720, (0, 0, 0), 'NO IMAGE', (255, 255, 255), 52)

                time.sleep(0.07)
                

            #timestamp = time.time()
            frames = [frame]

            self.queue_manager.memory_manager.write_images(frames, "camera_data_out", 0)



def camera_process_out(queue_manager, name):
    camera = RTSPStreamProcessor(
        queue_manager, 
        name = name, 
        rtsp_url = 'rtsp://admin:innotech@@192.168.1.65:554/live?transport=udp',
    )
    
    camera.start()