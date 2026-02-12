import threading
from queue import Empty
import cv2
import numpy as np
import time
import os
import shutil

from Process_image.frame_detection import FrameDetection
from Process_image.image_save import ImageSaver


def clear_folder(folder_path):
    """Удаляет все файлы и подкаталоги в указанной папке."""

    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
            print(f'Папка {folder_path} создана')
        except Exception as e:
            print(f'Ошибка при создании папки {folder_path}. Причина: {e}')

    try:
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f'Ошибка при удалении {file_path}. Причина: {e}')
    except Exception as e:
        print(f'Ошибка при доступе к папке {folder_path}. Причина: {e}')



class FrameDrawProcess:
    def __init__(self, queue_manager, name):
        self.name_process = str(name)
        self.queue_manager = queue_manager

        self.stop_proccess = False

        #self.image_save_brak = True

        self.frame_detection = FrameDetection()
        self.image_saver = ImageSaver()

        self.image_saver.initialize_last_numbers(folder_paths=[
            'Data_Image\Save_brak2'],
            prefix='image',
            )
        
        self.image_saver.initialize_last_numbers(folder_paths=[
            'Data_Image\Save_neutral'],
            prefix='image_neutral',
            )
        
        self.controls = {}
        self.init_control()

        self.frame_calibration = cv2.imread('29.jpg')

        clear_folder('Data_Image\Save_frame')

        self.control_thread = threading.Thread(target=self.control_update_thread)
        self.main_thread = threading.Thread(target=self.main_processing_thread)
        
        print(f'Процесс {self.name_process} запущен')
        queue_manager.download.put((self.name_process, True))


    def start(self):
        self.main_thread.start()
        self.control_thread.start()

    
    def stop(self):
        self.stop_proccess = True

        self.main_thread.join()
        self.control_thread.join()

        print(f'Процесс {self.name_process} остановлен')


    def control_update_thread(self):
        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            # try:
            #     #self.controls = self.queue_manager.control_draw.get(timeout=0.05)
            #     self.controls = self.queue_manager.control_draw.get_nowait()
            # except Empty:
            #     time.sleep(0.1)
            #     continue

            #self.queue_manager.control_draw_event.wait()
            self.controls = self.queue_manager.control_draw.get()
            #self.queue_manager.control_draw_event.clear()

            self.get_control()


    def init_control(self):
        try:
            self.controls = self.queue_manager.control_draw.get(timeout=1)
        except Empty:
            pass
        
        self.get_control()


    def get_control(self):
        #circles_info = self.controls['circles_info']
        #processing_time = self.controls['processing_time']
        #frame_id = self.controls['frame_id']
        #total = self.controls['total']
        #total_all = self.controls['total_all']

        #self.frame_crop = self.controls['frame_crop']

        self.snap_y = self.controls.get('snap_y', 200)
        self.y_delta = self.controls.get('y_delta', 50)
        self.x_min = self.controls.get('x_min', 100)
        self.x_max = self.controls.get('x_max', 400)

        self.fps = self.controls.get('fps', 20)
        self.draw = self.controls.get('draw', True)
        self.circles = self.controls.get('circles', True)
        self.rectangles = self.controls.get('rectangles', True)
        self.record_video = self.controls.get('record_video', False)
        self.save_image = self.controls.get('save_image', False)
        self.mode_image = self.controls.get('mode_image', 0)
        self.save_image_brak = self.controls.get('save_image_brak', False)
        self.camera_robot = self.controls.get('camera_robot', False)

        self.blend_alpha = self.controls.get('blend_alpha', 1)

        self.history = self.controls.get('history', 120)

        #print('self.controls', self.controls)
    

    def main_processing_thread(self):
        save_frames = []
        save_frames_2 = []

        while not self.queue_manager.stop_event.is_set() and not self.stop_proccess:
            # try:
            #     #data_frame = self.queue_manager.draw_queue.get(timeout=1)
            #     #data_frame = self.queue_manager.draw_queue.get(timeout=0.05)
            #     data_frame = self.queue_manager.draw_queue.get_nowait()
            # except Empty:
            #     time.sleep(0.01)
            #     continue
        
            data_frame = self.queue_manager.draw_queue.get()


            # self.queue_manager.draw_event.wait()
            # data_frame = self.queue_manager.draw_queue.get()
            # self.queue_manager.draw_event.clear()
            
           # print('Начинаю рисовать')

            id_memory = data_frame['id_memory']

            if not self.camera_robot:
                frames = self.queue_manager.memory_manager.read_images("process_data", id_memory)
            else:
                data_frame['camera_robot'] = self.camera_robot
                
                self.queue_manager.remove_old_frame_if_full(self.queue_manager.display_queue)
                self.queue_manager.display_queue.put(data_frame)
                self.queue_manager.display_event.set()

                time.sleep(0.015)

                self.queue_manager.memory_release_queue.put(id_memory)
            
                continue

            frames = self.queue_manager.memory_manager.read_images("process_data", id_memory)
            
            if len(frames) >= 0:
                frame = frames[self.mode_image if self.mode_image < len(frames) else len(frames) - 1]

                batch_metadata = data_frame['batch_metadata']
                batch_images = self.queue_manager.memory_manager.read_images("neuroun_data", id_memory, len(batch_metadata))

                #print('draw batch_images', len(batch_images), len(batch_metadata), 'id', id_memory)

                if self.blend_alpha < 1:
                    lower_bound = (0, 0, 150)  # нижняя граница (B, G, R)
                    upper_bound = (100, 100, 255)  # верхняя граница (B, G, R)

                    # Жёлтый цвет в BGR
                    new_color = (255, 0, 0)

                    self.frame_calibration = self.frame_detection.change_color_in_range(self.frame_calibration, lower_bound, upper_bound, new_color)

                    self.frame_calibration = self.frame_calibration[:frame.shape[0],:]
                    
                    # # Получение размеров целевого изображения
                    # target_height, target_width = frame.shape[:2]

                    # # Изменение размера исходного изображения под размеры целевого изображения
                    # self.frame_calibration = cv2.resize(self.frame_calibration, (target_width, target_height))
                    frame = self.frame_detection.blend_images(frame, self.frame_calibration, self.blend_alpha)

                combined_image = self.frame_detection.create_combined_image(frame, batch_images, batch_metadata)
                frame_add_spacer = self.frame_detection.add_black_space_below(frame, 8)
                frame_add_combine = self.frame_detection.combine_images_vertically(frame_add_spacer, combined_image)
                
                data_frame['frame_draw'] = frame_add_combine

                frame_draw = self.frame_detection.draw_on_frame(data_frame, self.controls)
  
                if self.history >= 120: 
                    if len(save_frames_2) > 0:
                        self.frame_detection.update_list_with_max_size(save_frames, save_frames_2, 120)

                    if len(save_frames) >= 120:
                        save_frames.pop(0)

                    save_frames.append(frame_draw)
                else:
                    if len(save_frames_2) >= 120:
                        save_frames_2.pop(0)
                
                    save_frames_2.append(frame_draw)

                    history_index = min(self.history, len(save_frames) - 1)
                    frame_draw = save_frames[history_index]

                data_frame['camera_robot'] = self.camera_robot

                frames_draw = [frame_draw]
                self.queue_manager.memory_manager.write_images(frames_draw, "display_data", id_memory)
                
                self.queue_manager.remove_old_frame_if_full(self.queue_manager.display_queue)
                self.queue_manager.display_queue.put(data_frame)
                self.queue_manager.display_event.set()

            if self.save_image_brak:
                for i, image in enumerate(batch_images):
                    category = batch_metadata[i].get('category', 'Good')
                    if category == "Bad":
                        value = batch_metadata[i].get('predict_value', 1)

                        #predict_value = round(batch_metadata[i].get('predict_value', 1), 2)
                        self.image_saver.save_image_with_incremental_number(image=image, 
                                                                    folder_path='Data_Image\Save_brak2', 
                                                                    prefix=f'image',
                                                                    add=f'_{value:.2f}'
                                                                    )

                    if category == "Neutral":
                        value = batch_metadata[i].get('predict_value', 1)
                        self.image_saver.save_image_with_incremental_number(image=image, 
                                                                    folder_path='Data_Image\Save_neutral', 
                                                                    prefix=f'image_neutral',
                                                                    add=f'_{value:.2f}'
                                                                    )


                frame_id = data_frame['frame_id']
                #cv2.imwrite(f'Data_Image\Save_frame\{frame_id}.jpg', frame_draw) 

            batch_images = []

        for frame_id, frame_draw in enumerate(save_frames):
            cv2.imwrite(f'Data_Image\Save_frame\{frame_id}.jpg', frame_draw) 
        

def frame_draw_processing(queue_manager, name):
    frame_draw = FrameDrawProcess(
        queue_manager, 
        name = name, 
    )
    
    frame_draw.start()
