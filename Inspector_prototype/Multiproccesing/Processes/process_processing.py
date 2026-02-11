import cv2
import time
import numpy as np
from queue import Empty


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
        'crop_bottom': 720,
        'crop_left': 0,
        'crop_right': 1280,
    }
    
    initialization = False
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление из очереди
        try:
            new_controls = control_processing.get_nowait()
            controls.update(new_controls)
            initialization = True
        except Empty:
            if not initialization:
                time.sleep(0.01)
                continue
        
        # Читаем метаданные кадра из очереди
        try:
            data_frame = queue_manager.frame_processor_queue.get_nowait()
        except Empty:
            time.sleep(0.01)
            continue
        
        id_memory = data_frame['id_memory']
        timestamp = data_frame['current_time']
        frame_id = data_frame['frame_id']
        
        # Читаем оригинальный кадр из памяти
        frames = queue_manager.memory_manager.read_images("camera_data", id_memory)
        
        if frames is None or len(frames) == 0:
            continue
        
        original_frame = frames[0]
        
        # Применяем обрезку изображения
        crop_top = controls.get('crop_top', 0)
        crop_bottom = controls.get('crop_bottom', original_frame.shape[0])
        crop_left = controls.get('crop_left', 0)
        crop_right = controls.get('crop_right', original_frame.shape[1])
        
        # Ограничиваем значения размерами изображения
        crop_top = max(0, min(crop_top, original_frame.shape[0]))
        crop_bottom = max(crop_top, min(crop_bottom, original_frame.shape[0]))
        crop_left = max(0, min(crop_left, original_frame.shape[1]))
        crop_right = max(crop_left, min(crop_right, original_frame.shape[1]))
        
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
        
        # Записываем обработанный кадр в память
        processed_frames = [processed_frame]
        queue_manager.memory_manager.write_images(processed_frames, "process_data", id_memory)
        
        # Отправляем метаданные в display_queue для App
        display_data = {
            'id_memory': id_memory,
            'current_time': timestamp,
            'frame_id': frame_id,
            'processed': True,  # Флаг что это обработанное изображение
        }
        
        queue_manager.remove_old_frame_if_full(queue_manager.display_queue)
        queue_manager.display_queue.put(display_data)
        
        # Освобождаем память камеры (опционально, можно делать позже)
        # queue_manager.memory_release_queue.put(id_memory)


def main(queue_manager, control_processing):
    """Главная функция процесса обработки"""
    process_processing(queue_manager, control_processing)
