"""
Универсальный процесс обработки региона
Может создаваться как несколько процессов с разными параметрами (processor_id, очереди и т.д.)
"""
import cv2
import time
import numpy as np
from queue import Empty
import sys
import os

# Добавляем путь к Utils для импорта FrameFPS
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Utils.frame_fps import FrameFPS
from Services.Region_processors import REGION_PROCESSORS, get_processor


def process_region_processor(queue_manager, control_processing, processor_id, input_queue):
    """
    Универсальный процесс обработки региона
    
    Args:
        queue_manager: Менеджер очередей
        control_processing: Очередь управления обработкой
        processor_id: ID процессора (1, 2, и т.д.)
        input_queue: Очередь для чтения регионов (region_processor_queue_1, region_processor_queue_2, и т.д.)
    """
    print(f'Процесс обработки региона {processor_id} запущен')
    
    # Отправляем сигнал готовности процесса
    try:
        queue_manager.process_ready_queue.put(f'proc_region_processor_{processor_id}')
        print(f"Region processor {processor_id} ready signal sent")
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
        'show_mask': False,
        'region_processor_type': None,  # 'rgb', 'bgr', 'grayscale' или None для HSV обработки
    }
    
    initialization = False
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление из очереди (неблокирующе)
        try:
            new_controls = control_processing.get_nowait()
            controls.update(new_controls)
            initialization = True
        except Empty:
            pass
        
        # Читаем метаданные региона из очереди
        try:
            region_data = input_queue.get_nowait()
        except Empty:
            time.sleep(0.01)
            continue
        
        # Время начала обработки
        processing_start_time = time.time()
        
        id_memory = region_data['id_memory']
        region_id = region_data.get('region_id', f'region_{processor_id}')
        frame_id = region_data.get('frame_id', 0)
        capture_time = region_data.get('capture_time', processing_start_time)
        region_coords = region_data.get('region_coords', {})  # {x1, y1, x2, y2}
        
        # Инициализируем timestamps если их нет
        if 'timestamps' not in region_data:
            region_data['timestamps'] = {}
        
        # Сохраняем время начала обработки региона
        region_data['timestamps'][f'{region_id}_processing_start'] = processing_start_time
        
        # Читаем оригинальный кадр из памяти
        frames = queue_manager.memory_manager.read_images("camera_data", id_memory)
        
        if frames is None or len(frames) == 0:
            continue
        
        original_frame = frames[0].copy()
        # Конвертируем в RGB если нужно
        if len(original_frame.shape) == 3 and original_frame.shape[2] == 3:
            # Проверяем формат (BGR или RGB)
            # Если это BGR, конвертируем в RGB
            original_frame = cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)
        
        # Вырезаем регион из изображения
        x1 = region_coords.get('x1', 0)
        y1 = region_coords.get('y1', 0)
        x2 = region_coords.get('x2', original_frame.shape[1])
        y2 = region_coords.get('y2', original_frame.shape[0])
        
        # Ограничиваем координаты размерами изображения
        orig_height = original_frame.shape[0]
        orig_width = original_frame.shape[1]
        x1 = max(0, min(x1, orig_width))
        x2 = max(x1, min(x2, orig_width))
        y1 = max(0, min(y1, orig_height))
        y2 = max(y1, min(y2, orig_height))
        
        region_frame = original_frame[y1:y2, x1:x2]
        
        # Проверяем тип процессора региона
        region_processor_type = controls.get('region_processor_type')
        
        # Применяем обработку если включена
        if controls['enable_processing']:
            # Если указан тип процессора региона (RGB/BGR/grayscale), используем классы напрямую
            if region_processor_type in ['rgb', 'bgr', 'grayscale']:
                # Получаем класс процессора из реестра
                processor_class = get_processor(region_processor_type)
                if processor_class:
                    # Создаем экземпляр процессора и обрабатываем регион
                    processor = processor_class()
                    processed_region = processor.process(region_frame, {})
                else:
                    print(f"Unknown processor class: {region_processor_type}, using original region")
                    processed_region = region_frame.copy()
            else:
                # Иначе используем HSV обработку (старый способ)
                # Конвертируем в HSV
                hsv_frame = cv2.cvtColor(region_frame, cv2.COLOR_RGB2HSV)
                
                # Создаем маску по цвету
                lower_bound = np.array([controls['hl'], controls['sl'], controls['vl']])
                upper_bound = np.array([controls['hm'], controls['sm'], controls['vm']])
                mask = cv2.inRange(hsv_frame, lower_bound, upper_bound)
                
                if controls['show_mask']:
                    # Показываем маску (конвертируем в RGB для отображения)
                    processed_region = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
                else:
                    # Применяем маску к региону
                    processed_region = cv2.bitwise_and(region_frame, region_frame, mask=mask)
        else:
            # Если обработка выключена, используем оригинальный регион
            processed_region = region_frame.copy()
        
        # Время окончания обработки
        processing_end_time = time.time()
        region_data['timestamps'][f'{region_id}_processing_end'] = processing_end_time
        
        # Вычисляем время обработки
        processing_time = processing_end_time - processing_start_time
        
        # Записываем обработанный регион в память
        # Используем гибкую схему индексации: id_memory * MAX_REGIONS + region_index
        # Где region_index вычисляется из region_id для уникальности
        # Для совместимости с текущей логикой используем processor_id как часть индекса
        # Но можно улучшить используя хеш от region_id
        MAX_REGIONS = 10  # Должно совпадать с Queue_Manager
        # Используем комбинацию processor_id и простой хеш от region_id для уникальности
        region_hash = hash(region_id) % MAX_REGIONS
        region_memory_index = id_memory * MAX_REGIONS + region_hash
        processed_regions = [processed_region]
        queue_manager.memory_manager.write_images(processed_regions, "region_data", region_memory_index)
        
        # Отправляем результат в объединяющий процесс
        region_result = {
            'id_memory': id_memory,  # Оригинальный id_memory кадра
            'region_id': region_id,
            'frame_id': frame_id,
            'capture_time': capture_time,
            'region_coords': region_coords,
            'processed': True,
            'timestamps': region_data['timestamps'],
            'processing_time': processing_time,
            'processor_id': processor_id,  # Идентификатор процессора
            'region_memory_index': region_memory_index  # Индекс в памяти region_data для этого процессора
        }
        
        queue_manager.remove_old_frame_if_full(queue_manager.region_results_queue)
        queue_manager.region_results_queue.put(region_result)
        
        print(f"Region processor {processor_id}: Processed region {region_id} for frame {frame_id}")


def main(queue_manager, control_processing, processor_id, input_queue):
    """
    Главная функция процесса обработки региона
    
    Args:
        queue_manager: Менеджер очередей
        control_processing: Очередь управления обработкой
        processor_id: ID процессора (1, 2, и т.д.)
        input_queue: Очередь для чтения регионов
    """
    process_region_processor(queue_manager, control_processing, processor_id, input_queue)
