"""
Процесс чтения кадров из файла (PNG)
При source='image' читает изображение и подаёт в пайплайн вместо камеры
"""
import cv2
import time
import numpy as np
import os
from queue import Empty
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))


def process_image_source(queue_manager, control_source):
    """
    При source='image' читает PNG и записывает в camera_data + frame_processor_queue.
    При source='camera' не делает ничего — кадры идут с камеры.
    """
    print("Процесс image_source запущен")
    
    try:
        queue_manager.process_ready_queue.put("proc_image_source")
    except Exception as e:
        print(f"Error sending ready signal: {e}")
    
    controls = {
        'source': 'camera',
        'image_path': 'Data/last_frame.png',
    }
    
    frame_counter = 0
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление (источник: camera/image)
        try:
            new_ctrl = control_source.get_nowait()
            controls.update(new_ctrl)
        except Empty:
            pass
        
        source = controls.get('source', 'camera')
        if source != 'image':
            time.sleep(0.05)
            continue
        
        image_path = controls.get('image_path', 'Data/last_frame.png')
        # Относительный путь — от корня проекта
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        full_path = os.path.join(base_dir, image_path)
        
        if not os.path.exists(full_path):
            time.sleep(0.1)
            continue
        
        try:
            frame = cv2.imread(full_path)
        except Exception as e:
            time.sleep(0.1)
            continue
        
        if frame is None or frame.size == 0:
            time.sleep(0.1)
            continue
        
        # BGR 3 канала
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            time.sleep(0.1)
            continue
        
        timestamp = time.time()
        id_memory = 0
        
        try:
            queue_manager.memory_manager.write_images([frame], "camera_data", id_memory)
        except Exception as e:
            time.sleep(0.05)
            continue
        
        data_frame = {
            'id_memory': id_memory,
            'capture_time': timestamp,
            'frame_counter': frame_counter,
            'frame_id': frame_counter % 121,
            'image_height': frame.shape[0],
            'image_width': frame.shape[1],
            'timestamps': {'capture': timestamp},
            'from_file': True,
        }
        
        frame_counter += 1
        
        try:
            queue_manager.remove_old_frame_if_full(queue_manager.frame_processor_queue)
            queue_manager.frame_processor_queue.put(data_frame)
        except Exception:
            pass
        
        time.sleep(0.1)  # ~10 FPS при чтении из файла


def main(queue_manager, control_source):
    process_image_source(queue_manager, control_source)
