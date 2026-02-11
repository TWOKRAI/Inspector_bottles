from PyQt5.QtCore import QThread, pyqtSignal
from queue import Empty
import os 
import cv2
import time


def save_images_to_folder(images, folder_path):
    """
    Сохраняет изображения из списка в указанную папку.

    :param images: Список изображений в формате, совместимом с OpenCV (например, массивы NumPy)
    :param folder_path: Путь к папке, в которую нужно сохранить изображения
    """
    # Создаем папку, если она не существует
    os.makedirs(folder_path, exist_ok=True)
    
    for i, img in enumerate(images):
        # Формируем имя файла
        file_name = f"image_{i}.png"
        file_path = os.path.join(folder_path, file_name)

        # Сохраняем изображение
        cv2.imwrite(file_path, img)
        #print(f"Изображение сохранено: {file_path}")
        
    print('Все изображения сохранены в папку Save_frame')


def clear_folder(folder_path):
    """
    Удаляет все файлы в указанной папке.

    :param folder_path: Путь к папке, которую нужно очистить
    """
    # Проверяем, существует ли папка
    if os.path.exists(folder_path):
        # Получаем список всех файлов в папке
        for file_name in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file_name)
            try:
                # Удаляем файл
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                    #print(f"Файл удален: {file_path}")
            except Exception as e:
                print(f"Ошибка при удалении файла {file_path}: {e}")
    else:
        print(f"Папка {folder_path} не существует.")


class UpdateImage(QThread):
    update_frame = pyqtSignal(list)

    def __init__(self, window_manager):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen

        self.data = None
        self.save_frame = []
        self.folder_save = 'Save_frame'

        clear_folder(self.folder_save)


    def run(self):
        while not self.queue_manager.stop_event.is_set():
            try:
                #data_frame = self.queue_manager.display_queue.get(timeout=0.05)
                data_frame = self.queue_manager.display_queue.get_nowait()
            except Empty:
                time.sleep(0.01)
                continue
            
            # self.queue_manager.display_event.wait()
            # data_frame = self.queue_manager.display_queue.get()
            # self.queue_manager.display_event.clear()
            

            if data_frame is not None:
                id_memory = data_frame.get('id_memory')
                camera_robot = data_frame.get('camera_robot', False)
                processed = data_frame.get('processed', False)
                
                frames = []
                
                # Проверяем настройку показа обработанного изображения
                show_processed = False
                if hasattr(self.window_manager, 'main_window'):
                    show_processed = self.window_manager.main_window.controls_processing.get('show_processed', False)
                
                if camera_robot:
                    # Читаем из camera_data_out (для робота)
                    frames_out = self.queue_manager.memory_manager.read_images('camera_data_out', 0)
                    if len(frames_out) > 0:
                        scale_factor = 0.7
                        height, width = frames_out[0].shape[:2]
                        new_width = int(width * scale_factor)
                        new_height = int(height * scale_factor)
                        frames_out_scaled = cv2.resize(frames_out[0], (new_width, new_height))
                        frame = frames_out_scaled[:, 40: width - 40]
                        frames.append(frame)
                        time.sleep(0.1)
                elif show_processed or processed:
                    # Читаем обработанное изображение из process_data
                    frames = self.queue_manager.memory_manager.read_images('process_data', id_memory)
                    if frames is None or len(frames) == 0:
                        # Если обработанного нет, читаем оригинал
                        frames = self.queue_manager.memory_manager.read_images('camera_data', id_memory)
                else:
                    # Читаем оригинальное изображение из camera_data
                    frames = self.queue_manager.memory_manager.read_images('camera_data', id_memory)

                if frames and len(frames) > 0:
                    self.update_frame.emit(frames)
                #self.update_frame.emit(frames)
                
                #print('time_all', time.time() - data_frame['current_time'])
                
                self.queue_manager.memory_release_queue.put(id_memory)
            
                #time.sleep(self.data['frame'] - 200)

            # if len(self.save_frame) >= 100:
            #     self.save_frame.pop(0)

            #self.save_frame.append(self.data['frame'])

        else:
            save_images_to_folder(self.save_frame, self.folder_save)