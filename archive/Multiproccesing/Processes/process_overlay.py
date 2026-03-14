"""
Процесс наложения overlay (текст, линии, прямоугольники) на изображения
Работает в конце пайплайна, создает отдельное изображение с overlay
"""
import cv2
import time
import numpy as np
from queue import Empty
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Utils.debug_log_helper import send_debug_log, send_debug_end


def process_overlay(queue_manager, control_overlay):
    """
    Процесс наложения overlay на изображения
    Читает изображения из display_queue, добавляет overlay и отправляет дальше
    """
    print("Процесс overlay запущен")
    
    try:
        queue_manager.process_ready_queue.put("proc_overlay")
    except Exception as e:
        print(f"Error sending ready signal: {e}")
    
    # Параметры по умолчанию
    # Overlay (FPS, прямоугольники регионов) применяется ТОЛЬКО к главному большому изображению
    # На регионах/вырезах свои рисунки (позже - из Redis и т.п.)
    controls = {
        'enable_overlay': True,  # Включение/выключение overlay (управляется Draw)
        'draw': True,  # Draw: включение/выключение рисования (FPS, прямоугольники регионов)
        'show_fps': True,  # Показывать FPS (только на главном изображении)
        'show_regions': True,  # Показывать прямоугольники регионов (только на главном)
        'show_region_names': True,  # Показывать имена регионов (только на главном)
    }
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление из очереди
        try:
            new_controls = control_overlay.get_nowait()
            controls.update(new_controls)
        except Empty:
            pass
        
        # Читаем данные кадра из overlay очереди
        try:
            data_frame = queue_manager.overlay_queue.get_nowait()
        except Empty:
            time.sleep(0.01)
            continue
        
        # Проверяем маркер логирования ПОСЛЕ получения кадра
        should_log = False
        if hasattr(queue_manager, 'debug_log_process_overlay'):
            if queue_manager.debug_log_process_overlay.is_set():
                should_log = True
                queue_manager.debug_log_process_overlay.clear()  # Сбрасываем маркер после получения кадра
                frame_id = data_frame.get('frame_id', 'unknown')
                print(f"  [process_overlay] ✓ Marker detected, will log frame_id={frame_id}")
        
        # Draw управляет отображением overlay (рисунки)
        draw_enabled = controls.get('draw', controls.get('enable_overlay', True))
        if not controls.get('enable_overlay', True) or not draw_enabled:
            # Если overlay выключен, просто передаем оригинальное изображение в display_queue
            # Без overlay, но с метриками
            queue_manager.remove_old_frame_if_full(queue_manager.display_queue)
            queue_manager.display_queue.put(data_frame)
            continue
        
        id_memory = data_frame.get('id_memory')
        fps = data_frame.get('fps', 0.0)
        # Получаем FPS из метрик если есть
        if fps == 0.0 and 'fps_after_processing' in data_frame:
            fps = data_frame.get('fps_after_processing', 0.0)
        
        processing_time_ms = data_frame.get('processing_time', 0.0)
        if isinstance(processing_time_ms, (int, float)):
            processing_time_ms = processing_time_ms * 1000  # Конвертируем в миллисекунды
        else:
            processing_time_ms = 0.0
        
        total_time_ms = data_frame.get('total_time_from_capture', 0.0)
        if isinstance(total_time_ms, (int, float)):
            total_time_ms = total_time_ms * 1000  # Конвертируем в миллисекунды
        else:
            total_time_ms = 0.0
        
        regions = data_frame.get('regions', [])
        selected_region_idx = data_frame.get('selected_region_idx', -1)
        
        # Читаем изображение из памяти
        frames = queue_manager.memory_manager.read_images("process_data", id_memory)
        if frames is None or len(frames) == 0:
            # Если нет обработанного, читаем оригинал
            frames = queue_manager.memory_manager.read_images("camera_data", id_memory)
        
        if frames is None or len(frames) == 0:
            continue
        
        frame = frames[0]
        # C-contiguous обязателен для cv2.putText/rectangle (shared memory даёт несовместимый layout)
        overlay_frame = np.ascontiguousarray(np.array(frame, dtype=np.uint8, copy=True))
        
        frame_id = data_frame.get('frame_id', 0)
        
        # Логирование кадра до overlay (только если маркер был установлен)
        if should_log:
            send_debug_log(
                queue_manager, 'current_frame', 'process_overlay',
                image=overlay_frame.copy() if overlay_frame is not None else None,
                step_name='before_overlay',
                description='Кадр до наложения overlay',
                metadata={
                    'fps': fps,
                    'processing_time_ms': processing_time_ms,
                    'total_time_ms': total_time_ms,
                    'regions_count': len(regions) if regions else 0,
                }
            )
        
        # Рисуем FPS и временные метрики (только на главном изображении)
        if draw_enabled and controls.get('show_fps', True):
            fps_text = f"FPS: {fps:.1f}" if fps > 0 else "FPS: 0.0"
            time_text = f"Proc: {processing_time_ms:.1f}ms | Total: {total_time_ms:.1f}ms"
            
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.7
            color_fps = (0, 255, 0)  # Зеленый (BGR)
            color_time = (255, 255, 0)  # Желтый (BGR)
            thickness = 2
            
            try:
                cv2.putText(overlay_frame, fps_text, (10, 30), font, font_scale, color_fps, thickness, cv2.LINE_AA)
                cv2.putText(overlay_frame, time_text, (10, 55), font, font_scale, color_time, thickness, cv2.LINE_AA)
            except Exception as e:
                print(f"Error drawing FPS overlay: {e}")
        
        # Рисуем прямоугольники регионов (только на главном изображении)
        if draw_enabled and controls.get('show_regions', True) and regions:
            height_img, width_img = overlay_frame.shape[:2]
            font = cv2.FONT_HERSHEY_SIMPLEX
            
            for i, r in enumerate(regions):
                if not isinstance(r, dict):
                    continue
                
                x1 = int(r.get('x1', 0))
                y1 = int(r.get('y1', 0))
                x2 = int(r.get('x2', 0))
                y2 = int(r.get('y2', 0))
                
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                
                # Ограничиваем в границах изображения
                x1 = max(0, min(x1, width_img))
                x2 = max(x1, min(x2, width_img))
                y1 = max(0, min(y1, height_img))
                y2 = max(y1, min(y2, height_img))
                
                if x1 >= x2 or y1 >= y2:
                    continue
                
                is_selected = (i == selected_region_idx)
                color = (0, 255, 0) if is_selected else (0, 165, 255)  # Зеленый выбран, оранжевый остальные
                th = 3 if is_selected else 2
                
                try:
                    cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), color, th)
                    
                    # Рисуем имя региона
                    if controls.get('show_region_names', True):
                        name = r.get('name', '')
                        if name:
                            cv2.putText(overlay_frame, name, (x1, max(15, y1 - 5)), font, 0.5, color, 1, cv2.LINE_AA)
                except Exception as e:
                    print(f"Error drawing region overlay: {e}")
        
        # Записываем изображение с overlay в отдельную память
        queue_manager.memory_manager.write_images([overlay_frame], "overlay_data", id_memory)
        
        # Логирование кадра после overlay (только если маркер был установлен)
        if should_log:
            send_debug_log(
                queue_manager, 'current_frame', 'process_overlay',
                image=overlay_frame,
                step_name='after_overlay',
                description='Кадр после наложения overlay',
                metadata={
                    'enable_overlay': controls.get('enable_overlay', True),
                    'draw': draw_enabled,
                    'show_fps': controls.get('show_fps', True),
                    'show_regions': controls.get('show_regions', True),
                    'show_region_names': controls.get('show_region_names', True),
                    'fps': fps,
                    'processing_time_ms': processing_time_ms,
                    'total_time_ms': total_time_ms,
                    'regions_count': len(regions) if regions else 0,
                    'selected_region_idx': selected_region_idx,
                }
            )
        
        # Обновляем данные кадра
        data_frame['overlay_applied'] = True
        data_frame['overlay_id_memory'] = id_memory
        data_frame['fps'] = fps
        data_frame['fps_after_processing'] = fps  # Для совместимости
        data_frame['processing_time'] = processing_time_ms / 1000.0
        data_frame['total_time_from_capture'] = total_time_ms / 1000.0
        
        # Отправляем в display_queue для отображения в UI
        queue_manager.remove_old_frame_if_full(queue_manager.display_queue)
        queue_manager.display_queue.put(data_frame)


def main(queue_manager, control_overlay):
    """Главная функция процесса overlay"""
    process_overlay(queue_manager, control_overlay)
