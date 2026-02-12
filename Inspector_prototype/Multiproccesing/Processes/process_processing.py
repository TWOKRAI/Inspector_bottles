import cv2
import time
import numpy as np
from queue import Empty
import sys
import os

# Добавляем путь к Utils для импорта FrameFPS
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Utils.frame_fps import FrameFPS


def process_processing(queue_manager, control_processing):
    """
    Процесс обработки изображений
    Читает кадры из frame_processor_queue, применяет обработку, записывает в process_data
    """
    print('Процесс обработки запущен')
    
    # Отправляем сигнал готовности процесса
    try:
        queue_manager.process_ready_queue.put('proc_processing')
        print("Processing process ready signal sent")
    except Exception as e:
        print(f"Error sending ready signal: {e}")
    
    # Параметры обработки по умолчанию
    # Используем большие значения по умолчанию для поддержки разных размеров
    controls = {
        'enable_processing': False,
        'hl': 0,  # H lower
        'sl': 0,  # S lower
        'vl': 0,  # V lower
        'hm': 255,  # H upper
        'sm': 255,  # S upper
        'vm': 255,  # V upper
        'show_mask': False,  # Показывать маску или обработанное изображение
        'crop_top': 0,
        'crop_bottom': 2160,  # Максимальная высота
        'crop_left': 0,
        'crop_right': 3840,  # Максимальная ширина
    }
    
    initialization = False
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление из очереди (неблокирующе)
        try:
            new_controls = control_processing.get_nowait()
            controls.update(new_controls)
            initialization = True
        except Empty:
            # Если инициализация еще не произошла, используем значения по умолчанию
            # но продолжаем обработку кадров
            pass
        
        # Читаем метаданные кадра из очереди
        try:
            data_frame = queue_manager.frame_processor_queue.get_nowait()
        except Empty:
            time.sleep(0.01)
            continue
        
        # Время начала обработки
        processing_start_time = time.time()
        
        id_memory = data_frame['id_memory']
        capture_time = data_frame.get('capture_time', processing_start_time)
        frame_id = data_frame.get('frame_id', 0)
        image_height = data_frame.get('image_height', 720)  # Оригинальная высота
        image_width = data_frame.get('image_width', 1280)   # Оригинальная ширина
        
        # Инициализируем timestamps если их нет
        if 'timestamps' not in data_frame:
            data_frame['timestamps'] = {}
        
        # Сохраняем время начала обработки
        data_frame['timestamps']['processing_start'] = processing_start_time
        
        # Читаем оригинальный кадр из памяти
        frames = queue_manager.memory_manager.read_images("camera_data", id_memory)
        
        if frames is None or len(frames) == 0:
            continue
        
        original_frame = frames[0]
        
        # Применяем обрезку изображения
        # Используем оригинальные размеры изображения для ограничения обрезки
        orig_height = original_frame.shape[0]
        orig_width = original_frame.shape[1]
        
        # Получаем значения обрезки из контролов (в пикселях от оригинального размера)
        crop_top = controls.get('crop_top', 0)
        crop_bottom = controls.get('crop_bottom', orig_height)
        crop_left = controls.get('crop_left', 0)
        crop_right = controls.get('crop_right', orig_width)
        
        # Ограничиваем значения размерами изображения
        # Если значения больше реального размера, используем полный размер
        crop_top = max(0, min(crop_top, orig_height))
        crop_bottom = max(crop_top, min(crop_bottom, orig_height))
        crop_left = max(0, min(crop_left, orig_width))
        crop_right = max(crop_left, min(crop_right, orig_width))
        
        # Если значения по умолчанию (максимальные), используем полный размер изображения
        if crop_bottom >= orig_height:
            crop_bottom = orig_height
        if crop_right >= orig_width:
            crop_right = orig_width
        
        cropped_frame = original_frame[crop_top:crop_bottom, crop_left:crop_right]
        
        # Применяем обработку если включена
        if controls['enable_processing']:
            # Конвертируем в HSV
            hsv_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_RGB2HSV)
            
            # Создаем маску по цвету
            lower_bound = np.array([controls['hl'], controls['sl'], controls['vl']])
            upper_bound = np.array([controls['hm'], controls['sm'], controls['vm']])
            mask = cv2.inRange(hsv_frame, lower_bound, upper_bound)
            
            if controls['show_mask']:
                # Показываем маску (конвертируем в RGB для отображения)
                processed_frame = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
            else:
                # Применяем маску к обрезанному изображению
                processed_frame = cv2.bitwise_and(cropped_frame, cropped_frame, mask=mask)
        else:
            # Если обработка выключена, используем обрезанное изображение
            processed_frame = cropped_frame.copy()
        
        # Время окончания обработки
        processing_end_time = time.time()
        data_frame['timestamps']['processing_end'] = processing_end_time
        
        # Вычисляем время обработки
        processing_time = processing_end_time - processing_start_time
        total_time_from_capture = processing_end_time - capture_time
        
        # Записываем обработанный кадр в память
        processed_frames = [processed_frame]
        queue_manager.memory_manager.write_images(processed_frames, "process_data", id_memory)
        
        # Отправляем метаданные в post_processor_queue для пост-обработки
        post_processing_data = {
            'id_memory': id_memory,
            'capture_time': capture_time,  # Время захвата кадра
            'frame_id': frame_id,
            'processed': True,  # Флаг что это обработанное изображение
            'timestamps': data_frame['timestamps'],  # Все временные метки
            'processing_time': processing_time,  # Время обработки в секундах
            'total_time_from_capture': total_time_from_capture,  # Общее время от захвата до конца обработки
            'image_height': image_height,  # Оригинальная высота изображения
            'image_width': image_width    # Оригинальная ширина изображения
        }
        
        queue_manager.remove_old_frame_if_full(queue_manager.post_processor_queue)
        queue_manager.post_processor_queue.put(post_processing_data)
        
        # Освобождаем память камеры (опционально, можно делать позже)
        # queue_manager.memory_release_queue.put(id_memory)


def main(queue_manager, control_processing):
    """Главная функция процесса обработки"""
    process_processing(queue_manager, control_processing)
