"""
Объединяющий процесс для регионов
Собирает результаты обработки регионов по frame_id и отправляет объединенный результат дальше
"""
import cv2
import time
import numpy as np
from queue import Empty
from collections import defaultdict
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Utils.debug_log_helper import send_debug_log


def process_region_merger(queue_manager, control_post_processing):
    """
    Объединяющий процесс для регионов
    Принимает результаты обработки регионов, собирает их по frame_id
    и отправляет объединенный результат дальше
    """
    print('Объединяющий процесс регионов запущен')
    
    # Отправляем сигнал готовности процесса
    try:
        queue_manager.process_ready_queue.put('proc_region_merger')
        print("Region merger ready signal sent")
    except Exception as e:
        print(f"Error sending ready signal: {e}")
    
    # Словарь для хранения результатов по frame_id
    # Структура: {frame_id: {'regions': [...], 'capture_time': ..., 'id_memory': ..., 'expected_regions': set(...)}}
    pending_frames = defaultdict(lambda: {
        'regions': [],
        'capture_time': None,
        'id_memory': None,
        'expected_regions': set(),
        'timestamps': {}
    })
    
    # Параметры по умолчанию
    controls = {
        'regions': [],
        'enable_post_processing': False,
    }
    
    # Таймаут для ожидания регионов (в секундах)
    REGION_TIMEOUT = 5.0
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление из очереди
        try:
            new_controls = control_post_processing.get_nowait()
            controls.update(new_controls)
        except Empty:
            pass
        
        # Читаем результат обработки региона
        try:
            region_result = queue_manager.region_results_queue.get_nowait()
        except Empty:
            # Проверяем таймауты для ожидающих кадров
            current_time = time.time()
            frames_to_remove = []
            
            for frame_id, frame_data in pending_frames.items():
                if frame_data['capture_time']:
                    elapsed = current_time - frame_data['capture_time']
                    if elapsed > REGION_TIMEOUT:
                        print(f"Timeout for frame {frame_id}, sending incomplete result")
                        frames_to_remove.append(frame_id)
                        
                        # Проверяем маркер логирования для таймаута
                        should_log_timeout = False
                        if hasattr(queue_manager, 'debug_log_process_region_merger'):
                            if queue_manager.debug_log_process_region_merger.is_set():
                                should_log_timeout = True
                                queue_manager.debug_log_process_region_merger.clear()
                        
                        # Отправляем неполный результат
                        _send_merged_result(queue_manager, frame_id, frame_data, should_log=should_log_timeout)
            
            for frame_id in frames_to_remove:
                del pending_frames[frame_id]
            
            time.sleep(0.01)
            continue
        
        frame_id = region_result['frame_id']
        region_id = region_result['region_id']
        id_memory = region_result['id_memory']
        capture_time = region_result.get('capture_time', time.time())
        
        # Инициализируем или обновляем данные кадра
        if frame_id not in pending_frames:
            pending_frames[frame_id]['id_memory'] = id_memory
            pending_frames[frame_id]['capture_time'] = capture_time
            pending_frames[frame_id]['timestamps'] = region_result.get('timestamps', {}).copy()
        
        # Добавляем регион в список результатов
        pending_frames[frame_id]['regions'].append({
            'region_id': region_id,
            'region_coords': region_result.get('region_coords', {}),
            'processor_id': region_result.get('processor_id', 0),
            'processing_time': region_result.get('processing_time', 0),
            'timestamps': region_result.get('timestamps', {}),
            'region_memory_index': region_result.get('region_memory_index')  # Сохраняем индекс памяти региона
        })
        
        # Обновляем ожидаемые регионы из конфигурации
        if not pending_frames[frame_id]['expected_regions']:
            # Определяем ожидаемые регионы на основе конфигурации из controls
            regions = controls.get('regions', [])
            expected_regions = set()
            for r in regions:
                if isinstance(r, dict):
                    region_name = r.get('name')
                    enabled = r.get('enabled', True)
                    if region_name and enabled:
                        expected_regions.add(region_name)
            pending_frames[frame_id]['expected_regions'] = expected_regions
        
        # Проверяем, все ли регионы получены
        received_regions = {r['region_id'] for r in pending_frames[frame_id]['regions']}
        expected_regions = pending_frames[frame_id]['expected_regions']
        
        if received_regions == expected_regions:
            # Все регионы получены, объединяем и отправляем
            print(f"All regions received for frame {frame_id}, merging...")
            
            # Проверяем маркер логирования ПОСЛЕ получения всех регионов
            should_log_merger = False
            if hasattr(queue_manager, 'debug_log_process_region_merger'):
                if queue_manager.debug_log_process_region_merger.is_set():
                    should_log_merger = True
                    queue_manager.debug_log_process_region_merger.clear()  # Сбрасываем маркер
                    print(f"  [process_region_merger] Marker detected and cleared, will log frame_id={frame_id}")
            
            _send_merged_result(queue_manager, frame_id, pending_frames[frame_id], should_log=should_log_merger)
            del pending_frames[frame_id]
        else:
            print(f"Frame {frame_id}: Received {len(received_regions)}/{len(expected_regions)} regions")
            print(f"  Received: {received_regions}")
            print(f"  Expected: {expected_regions}")


def _send_merged_result(queue_manager, frame_id, frame_data, should_log=False):
    """
    Объединяет регионы в одно изображение и отправляет результат дальше
    """
    try:
        id_memory = frame_data['id_memory']
        capture_time = frame_data.get('capture_time', time.time())
        regions = frame_data['regions']
        
        # Читаем оригинальное изображение для получения размеров
        frames = queue_manager.memory_manager.read_images("camera_data", id_memory)
        if frames is None or len(frames) == 0:
            print(f"Cannot read original frame for frame {frame_id}")
            return
        
        original_frame = frames[0].copy()
        if len(original_frame.shape) == 3 and original_frame.shape[2] == 3:
            original_frame = cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)
        
        # Логирование начала объединения (только если маркер был установлен)
        if should_log:
            send_debug_log(
                queue_manager, 'current_frame', 'process_region_merger',
                step_name='merge_start',
                description=f'Начало объединения {len(regions)} регионов',
                metadata={
                    'regions_count': len(regions),
                    'regions_info': [{'region_id': r['region_id'], 'processor_id': r.get('processor_id')} 
                                    for r in regions]
                }
            )
        
        # Создаем результирующее изображение (пока просто копируем оригинал)
        # В будущем можно накладывать обработанные регионы обратно
        merged_frame = original_frame.copy()
        
        # Читаем обработанные регионы и накладываем их обратно
        # Для каждого региона читаем из памяти и вставляем в нужное место
        for region_info in regions:
            region_id = region_info['region_id']
            region_coords = region_info['region_coords']
            processor_id = region_info['processor_id']
            
            # Используем сохраненный индекс памяти региона если есть
            region_memory_index = region_info.get('region_memory_index')
            if region_memory_index is None:
                # Если индекс не сохранен, вычисляем его
                MAX_REGIONS = 10  # Должно совпадать с Queue_Manager
                region_hash = hash(region_id) % MAX_REGIONS
                region_memory_index = id_memory * MAX_REGIONS + region_hash
            
            # Читаем обработанный регион из памяти
            processed_regions = queue_manager.memory_manager.read_images("region_data", region_memory_index)
            
            if processed_regions and len(processed_regions) > 0:
                processed_region = processed_regions[0]
                
                # Вставляем обработанный регион обратно в изображение
                x1 = region_coords.get('x1', 0)
                y1 = region_coords.get('y1', 0)
                x2 = region_coords.get('x2', merged_frame.shape[1])
                y2 = region_coords.get('y2', merged_frame.shape[0])
                
                # Ограничиваем координаты
                orig_height = merged_frame.shape[0]
                orig_width = merged_frame.shape[1]
                x1 = max(0, min(x1, orig_width))
                x2 = max(x1, min(x2, orig_width))
                y1 = max(0, min(y1, orig_height))
                y2 = max(y1, min(y2, orig_height))
                
                # Изменяем размер обработанного региона если нужно
                region_height = y2 - y1
                region_width = x2 - x1
                
                # Проверяем валидность размеров перед ресайзом
                if region_height > 0 and region_width > 0:
                    if processed_region.shape[0] != region_height or processed_region.shape[1] != region_width:
                        # Проверяем, что обработанный регион не пустой
                        if processed_region.size > 0 and processed_region.shape[0] > 0 and processed_region.shape[1] > 0:
                            try:
                                processed_region = cv2.resize(processed_region, (region_width, region_height))
                            except Exception as e:
                                print(f"Error resizing region {region_id}: {e}")
                                print(f"  processed_region shape: {processed_region.shape}")
                                print(f"  target size: ({region_width}, {region_height})")
                                continue  # Пропускаем этот регион
                        else:
                            print(f"Warning: processed_region {region_id} is empty, skipping")
                            continue
                    
                    # Вставляем регион обратно
                    if region_height <= merged_frame.shape[0] and region_width <= merged_frame.shape[1]:
                        merged_frame[y1:y2, x1:x2] = processed_region
                    else:
                        print(f"Warning: Region {region_id} coordinates out of bounds, skipping")
                else:
                    print(f"Warning: Invalid region size for {region_id}: {region_width}x{region_height}, skipping")
                
                # Логирование вставки региона (только если маркер был установлен)
                if should_log:
                    send_debug_log(
                        queue_manager, 'current_frame', 'process_region_merger',
                        step_name=f'region_inserted_{region_id}',
                        description=f'Вставлен регион {region_id}',
                        metadata={
                            'region_id': region_id,
                            'processor_id': processor_id,
                            'region_coords': region_coords,
                            'region_size': f"{processed_region.shape[0]}x{processed_region.shape[1]}",
                        }
                    )
        
        # Вычисляем общее время обработки
        total_processing_time = sum(r.get('processing_time', 0) for r in regions)
        
        # Объединяем timestamps
        merged_timestamps = frame_data.get('timestamps', {}).copy()
        for region_info in regions:
            region_timestamps = region_info.get('timestamps', {})
            merged_timestamps.update(region_timestamps)
        
        merge_time = time.time()
        merged_timestamps['merge_time'] = merge_time
        
        # Записываем объединенный кадр в память
        queue_manager.memory_manager.write_images([merged_frame], "process_data", id_memory)
        
        # Логирование объединенного кадра (только если маркер был установлен)
        if should_log:
            send_debug_log(
                queue_manager, 'current_frame', 'process_region_merger',
                image=merged_frame,
                step_name='merged',
                description='Объединенный кадр со всеми регионами',
                metadata={
                    'regions_count': len(regions),
                    'total_processing_time': total_processing_time,
                    'merge_time': merge_time,
                    'total_time_from_capture': merge_time - capture_time,
                }
            )
        
        # Отправляем результат дальше (в post_processor_queue)
        merged_result = {
            'id_memory': id_memory,
            'capture_time': capture_time,
            'frame_id': frame_id,
            'processed': True,
            'timestamps': merged_timestamps,
            'processing_time': total_processing_time,
            'total_time_from_capture': merge_time - capture_time,
            'image_height': merged_frame.shape[0],
            'image_width': merged_frame.shape[1],
            'regions_processed': len(regions),
            'regions_info': [{'region_id': r['region_id'], 'processor_id': r['processor_id']} 
                            for r in regions]
        }
        
        queue_manager.remove_old_frame_if_full(queue_manager.post_processor_queue)
        queue_manager.post_processor_queue.put(merged_result)
        
        print(f"Merged result sent for frame {frame_id} with {len(regions)} regions")
        
    except Exception as e:
        print(f"Error merging result for frame {frame_id}: {e}")
        import traceback
        traceback.print_exc()


def main(queue_manager, control_post_processing):
    """Главная функция объединяющего процесса"""
    process_region_merger(queue_manager, control_post_processing)
