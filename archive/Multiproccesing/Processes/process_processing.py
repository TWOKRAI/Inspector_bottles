import cv2
import time
import numpy as np
from queue import Empty
import sys
import os

# Добавляем путь к Utils для импорта FrameFPS
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Utils.frame_fps import FrameFPS
from Utils.debug_log_helper import send_debug_log, send_debug_end


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
        'enable_region_mode': False,  # Режим обработки регионов
        'region_config': {},  # Конфигурация регионов: {region_id: {processor_id, x1, y1, x2, y2}}
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
        
        # Проверяем маркер логирования ПОСЛЕ получения кадра
        should_log = False
        if hasattr(queue_manager, 'debug_log_process_processing'):
            try:
                marker = queue_manager.debug_log_process_processing
                if marker.is_set():
                    should_log = True
                    marker.clear()  # Сбрасываем маркер после получения кадра
                    frame_id = data_frame.get('frame_id', 'unknown')
                    print(f"  [process_processing] ✓ Marker detected, will log frame_id={frame_id}")
            except Exception as e:
                print(f"  [process_processing] Error checking marker: {e}")
        
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
        
        original_frame = frames[0].copy()
        # Единая конвертация в RGB в начале пайплайна — дальше везде (HSV, отображение в PyQt) ожидается RGB
        if len(original_frame.shape) == 3 and original_frame.shape[2] == 3:
            original_frame = cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)
        
        # Логирование оригинального кадра (только если маркер был установлен)
        if should_log:
            # Используем реальный frame_id из кадра, но сохраняем в папку current_frame
            send_debug_log(
                queue_manager, 'current_frame', 'process_processing',
                image=original_frame,
                step_name='original',
                description='Оригинальный кадр из камеры',
                metadata={
                    'id_memory': id_memory,
                    'frame_id': frame_id,
                    'image_height': image_height,
                    'image_width': image_width,
                    'capture_time': capture_time,
                }
            )
        
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
        
        # Логирование обрезанного кадра (только если маркер был установлен)
        if should_log:
            send_debug_log(
                queue_manager, 'current_frame', 'process_processing',
                image=cropped_frame,
                step_name='cropped',
                description='Обрезанный кадр',
                metadata={
                    'crop_top': crop_top,
                    'crop_bottom': crop_bottom,
                    'crop_left': crop_left,
                    'crop_right': crop_right,
                    'cropped_size': f"{cropped_frame.shape[0]}x{cropped_frame.shape[1]}",
                    'enable_processing': controls.get('enable_processing', False),
                }
            )
        
        # Проверяем режим обработки регионов
        if controls.get('enable_region_mode', False):
            # Режим регионов: разделяем на регионы и отправляем в процессоры
            region_config = controls.get('region_config', {})
            
            if region_config:
                # Отправляем каждый регион в соответствующий процессор
                for region_id, region_info in region_config.items():
                    processor_id = region_info.get('processor_id', 1)
                    region_coords = {
                        'x1': region_info.get('x1', 0),
                        'y1': region_info.get('y1', 0),
                        'x2': region_info.get('x2', orig_width),
                        'y2': region_info.get('y2', orig_height),
                    }
                    
                    # Выбираем очередь в зависимости от процессора
                    if processor_id == 1:
                        target_queue = queue_manager.region_processor_queue_1
                    elif processor_id == 2:
                        target_queue = queue_manager.region_processor_queue_2
                    else:
                        print(f"Unknown processor_id {processor_id} for region {region_id}")
                        continue
                    
                    # Создаем данные региона
                    region_data = {
                        'id_memory': id_memory,
                        'region_id': region_id,
                        'frame_id': frame_id,
                        'capture_time': capture_time,
                        'region_coords': region_coords,
                        'timestamps': data_frame.get('timestamps', {}).copy(),
                        'image_height': image_height,
                        'image_width': image_width,
                    }
                    
                    # Отправляем в очередь процессора
                    queue_manager.remove_old_frame_if_full(target_queue)
                    target_queue.put(region_data)
                    print(f"Sent region {region_id} to processor {processor_id} for frame {frame_id}")
                
                # В режиме регионов не обрабатываем изображение здесь, только отправляем регионы
                # Объединяющий процесс соберет результаты
                # Но все равно нужно отправить кадр в post_processor_queue для дальнейшей обработки
                # Отправляем оригинальный кадр (регионы обработаются отдельно и объединятся)
                post_processing_data = {
                    'id_memory': id_memory,
                    'capture_time': capture_time,
                    'frame_id': frame_id,
                    'processed': False,  # Регионы обрабатываются отдельно
                    'timestamps': data_frame.get('timestamps', {}),
                    'processing_time': 0.0,
                    'total_time_from_capture': time.time() - capture_time,
                    'image_height': image_height,
                    'image_width': image_width
                }
                queue_manager.remove_old_frame_if_full(queue_manager.post_processor_queue)
                queue_manager.post_processor_queue.put(post_processing_data)
                continue
            else:
                print("Region mode enabled but no region_config provided, falling back to normal mode")
        
        # Применяем обработку если включена
        if controls['enable_processing']:
            # Конвертируем в HSV
            hsv_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_RGB2HSV)
            
            # Логирование HSV кадра (без изображения, только метаданные)
            if should_log:
                send_debug_log(
                    queue_manager, 'current_frame', 'process_processing',
                    step_name='hsv',
                    description='Конвертация в HSV',
                    metadata={}
                )
            
            # Создаем маску по цвету
            lower_bound = np.array([controls['hl'], controls['sl'], controls['vl']])
            upper_bound = np.array([controls['hm'], controls['sm'], controls['vm']])
            mask = cv2.inRange(hsv_frame, lower_bound, upper_bound)
            
            # Логирование маски
            if should_log:
                mask_rgb = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
                send_debug_log(
                    queue_manager, 'current_frame', 'process_processing',
                    image=mask_rgb,
                    step_name='mask',
                    description='Маска по цвету',
                    metadata={
                        'lower_bound': [controls['hl'], controls['sl'], controls['vl']],
                        'upper_bound': [controls['hm'], controls['sm'], controls['vm']],
                    }
                )
            
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
        
        # Логирование обработанного кадра (только если маркер был установлен)
        if should_log:
            send_debug_log(
                queue_manager, 'current_frame', 'process_processing',
                image=processed_frame,
                step_name='processed',
                description='Обработанный кадр',
                metadata={
                    'enable_processing': controls['enable_processing'],
                    'show_mask': controls.get('show_mask', False),
                    'processing_time': processing_time,
                    'total_time_from_capture': total_time_from_capture,
                }
            )
        
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
