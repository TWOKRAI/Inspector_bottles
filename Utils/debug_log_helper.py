"""
Вспомогательные функции для отладочного логирования
Процессы используют эти функции для сохранения изображений и отправки метаданных
"""
import os
import cv2
import numpy as np
import time


def save_debug_image(image: np.ndarray, base_dir: str, frame_id, 
                     process_name: str, step_name: str, counter: int) -> str:
    """
    Сохранить изображение для отладки
    
    Returns:
        Относительный путь к сохраненному изображению (от base_dir)
    """
    try:
        # Проверяем, что изображение не пустое
        if image is None or image.size == 0:
            print(f"Warning: Empty image passed to save_debug_image (process={process_name}, step={step_name})")
            return ""
        
        # Проверяем размеры изображения
        if len(image.shape) == 0 or (len(image.shape) >= 2 and (image.shape[0] == 0 or image.shape[1] == 0)):
            print(f"Warning: Invalid image dimensions {image.shape} (process={process_name}, step={step_name})")
            return ""
        
        # Создаем структуру папок
        frame_dir = os.path.join(base_dir, f"frame_{frame_id}")
        images_dir = os.path.join(frame_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        
        # Генерируем имя файла
        safe_process = process_name.replace('/', '_').replace('\\', '_')
        safe_step = step_name.replace('/', '_').replace('\\', '_') if step_name else f"step_{counter}"
        filename = f"{counter:03d}_{safe_process}_{safe_step}.png"
        filepath = os.path.join(images_dir, filename)
        
        # Конвертируем RGB в BGR для OpenCV
        if len(image.shape) == 3 and image.shape[2] == 3:
            try:
                save_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            except:
                save_image = image
        else:
            save_image = image
        
        # Сохраняем
        success = cv2.imwrite(filepath, save_image)
        if not success:
            print(f"Warning: Failed to save debug image to {filepath}")
            return ""
        
        # Возвращаем относительный путь
        rel_path = os.path.join("images", filename).replace('\\', '/')
        return rel_path
    except Exception as e:
        print(f"Error saving debug image: {e}")
        import traceback
        traceback.print_exc()
        return ""


def send_debug_log(queue_manager, frame_id, process_name: str, 
                   image: np.ndarray = None, step_name: str = "",
                   description: str = "", metadata: dict = None):
    """
    Отправить лог в очередь отладки
    
    Если передано изображение, оно будет сохранено и путь добавлен в лог
    """
    if not hasattr(queue_manager, 'debug_log_queue'):
        return
    
    try:
        base_dir = os.path.join(os.path.dirname(__file__), '../Data/debug_logs')
        base_dir = os.path.abspath(base_dir)
        
        # Сохраняем изображение если есть
        image_path = None
        if image is not None:
            # Используем счетчик на основе timestamp для уникальности
            counter = int(time.time() * 1000) % 10000
            image_path = save_debug_image(image, base_dir, frame_id, process_name, step_name, counter)
        
        # Отправляем метаданные
        queue_manager.remove_old_frame_if_full(queue_manager.debug_log_queue)
        queue_manager.debug_log_queue.put({
            'type': 'step',
            'frame_id': frame_id,
            'process_name': process_name,
            'step_name': step_name,
            'description': description,
            'metadata': metadata or {},
            'image_path': image_path,
            'timestamp': time.time()
        })
    except Exception as e:
        print(f"Error sending debug log: {e}")


def send_debug_end(queue_manager, frame_id):
    """Отправить сигнал завершения сбора данных для кадра"""
    if not hasattr(queue_manager, 'debug_log_queue'):
        return
    
    try:
        queue_manager.debug_log_queue.put({
            'type': 'end',
            'frame_id': frame_id
        })
    except Exception as e:
        print(f"Error sending debug end signal: {e}")

