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
        # Счетчики для вычисления FPS на основе времени
        last_capture_time = None
        frame_count = 0
        fps_start_time = time.time()
        
        while not self.queue_manager.stop_event.is_set():
            try:
                #data_frame = self.queue_manager.display_queue.get(timeout=0.05)
                data_frame = self.queue_manager.display_queue.get_nowait()
            except Empty:
                time.sleep(0.01)
                continue
            
            if data_frame is not None:
                # Время начала отображения
                display_start_time = time.time()
                
                id_memory = data_frame.get('id_memory')
                camera_robot = data_frame.get('camera_robot', False)
                processed = data_frame.get('processed', False)
                capture_time = data_frame.get('capture_time', display_start_time)
                timestamps = data_frame.get('timestamps', {})
                processing_time = data_frame.get('processing_time', 0.0)
                total_time_from_capture = data_frame.get('total_time_from_capture', 0.0)
                image_height = data_frame.get('image_height', 0)
                image_width = data_frame.get('image_width', 0)
                
                # Обновляем размер изображения в главном окне если он изменился
                if hasattr(self.window_manager, 'main_window'):
                    main_window = self.window_manager.main_window
                    if image_height > 0 and image_width > 0:
                        if main_window.image_height != image_height or main_window.image_width != image_width:
                            main_window.image_height = image_height
                            main_window.image_width = image_width
                            main_window.update_fps_display()
                
                # Вычисляем FPS на основе времени между кадрами
                if last_capture_time is not None:
                    time_between_frames = capture_time - last_capture_time
                    if time_between_frames > 0:
                        current_fps = 1.0 / time_between_frames
                    else:
                        current_fps = 0.0
                else:
                    current_fps = 0.0
                
                last_capture_time = capture_time
                frame_count += 1
                
                # Вычисляем средний FPS за последнюю секунду
                elapsed_time = display_start_time - fps_start_time
                if elapsed_time >= 1.0:
                    avg_fps = frame_count / elapsed_time
                    frame_count = 0
                    fps_start_time = display_start_time
                else:
                    avg_fps = current_fps if current_fps > 0 else 0.0
                
                # Время окончания отображения
                display_end_time = time.time()
                display_time = display_end_time - display_start_time
                total_time_to_display = display_end_time - capture_time
                
                # Обновляем FPS и временные метрики в главном окне
                if hasattr(self.window_manager, 'main_window'):
                    main_window = self.window_manager.main_window
                    main_window.fps_after_processing = avg_fps
                    main_window.processing_time_ms = processing_time * 1000  # В миллисекундах
                    main_window.total_time_ms = total_time_to_display * 1000  # В миллисекундах
                    main_window.update_fps_display()
                
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