# App/Core/Threads/thread_image_update.py
# -*- coding: utf-8 -*-
"""
UpdateImage — поток получения и обработки кадров от бэкенда.

Ответственность:
  - Чтение из display_queue (shared memory через queue_manager)
  - Вычисление метрик (FPS, время обработки)
  - Эмиссия сигнала frame_ready с данными и метриками

НЕ делает:
  - НЕ пишет напрямую в MainWindow (только сигнал!)
  - НЕ хранит метрики в атрибутах (передаёт в сигнале)
  - НЕ знает про UI (нет Qt виджетов, только QThread)

Архитектура:
  UpdateImage (QThread)
    └── run() → читает из queue_manager.display_queue
          └── frame_ready.emit(frames, metrics)
                ├── frames: List[np.ndarray] — кадры для отображения
                └── metrics: dict — {'fps', 'proc_time_ms', 'total_time_ms', 'width', 'height'}
"""

from typing import List, Dict, Any, Optional
from queue import Empty
import time
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal


class UpdateImage(QThread):
    """
    Поток получения кадров от бэкенда.
    
    Единственный публичный интерфейс — сигнал frame_ready.
    Никаких прямых вызовов в MainWindow!
    """
    
    # Сигнал с данными: кадры + метрики
    frame_ready = pyqtSignal(list, dict)  # frames: List[np.ndarray], metrics: dict
    
    def __init__(
        self,
        queue_manager: Any,
        stop_event: Any,
        parent=None,
    ):
        super().__init__(parent)
        
        # Зависимости (только для чтения из очереди)
        self._queue_manager = queue_manager
        self._stop_event = stop_event
        
        # Runtime state (только для вычислений, не для хранения между кадрами!)
        self._fps_start_time: float = time.time()
        self._frame_count: int = 0
        self._last_capture_time: Optional[float] = None
    
    def run(self) -> None:
        """Основной цикл потока."""
        while not self._stop_event.is_set():
            try:
                # Неблокирующее чтение с таймаутом
                data_frame = self._queue_manager.display_queue.get(timeout=0.05)
                
            except Empty:
                # Нет данных — небольшая пауза чтобы не грузить CPU
                time.sleep(0.001)
                continue
            
            if data_frame is None:
                continue
            
            # Обработка кадра
            self._process_frame(data_frame)
            
            # Освобождение памяти
            try:
                id_memory = data_frame.get('id_memory')
                if id_memory is not None:
                    self._queue_manager.memory_release_queue.put(id_memory)
            except Exception:
                pass
    
    def _process_frame(self, data_frame: Dict[str, Any]) -> None:
        """
        Обработка одного кадра: чтение из памяти, вычисление метрик, эмиссия сигнала.
        """
        import cv2  # Ленивый импорт
        
        # Время начала обработки
        process_start = time.time()
        
        # Извлекаем метаданные
        id_memory = data_frame.get('id_memory', 0)
        camera_robot = data_frame.get('camera_robot', False)
        processed = data_frame.get('processed', False)
        capture_time = data_frame.get('capture_time', process_start)
        processing_time = data_frame.get('processing_time', 0.0)  # От бэкенда
        image_height = data_frame.get('image_height', 0)
        image_width = data_frame.get('image_width', 0)
        
        # ═════════════════════════════════════════════════════════════════
        # Вычисление FPS (на основе времени между кадрами)
        # ═════════════════════════════════════════════════════════════════
        
        current_fps = 0.0
        
        if self._last_capture_time is not None:
            time_between = capture_time - self._last_capture_time
            if time_between > 0:
                current_fps = 1.0 / time_between
        
        self._last_capture_time = capture_time
        self._frame_count += 1
        
        # Средний FPS за последнюю секунду
        elapsed = process_start - self._fps_start_time
        avg_fps = current_fps
        
        if elapsed >= 1.0:
            avg_fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_start_time = process_start
        
        # ═════════════════════════════════════════════════════════════════
        # Чтение кадров из shared memory
        # ═════════════════════════════════════════════════════════════════
        
        frames = self._read_frames(
            id_memory=id_memory,
            camera_robot=camera_robot,
            processed=processed,
        )
        
        if not frames:
            return  # Нет кадров — не эмитим
        
        # Время окончания обработки
        process_end = time.time()
        display_time_ms = (process_end - process_start) * 1000
        total_time_ms = (process_end - capture_time) * 1000
        
        # ═════════════════════════════════════════════════════════════════
        # Формирование метрик
        # ═════════════════════════════════════════════════════════════════
        
        metrics = {
            'fps': avg_fps,
            'proc_time_ms': processing_time * 1000,  # От бэкенда
            'display_time_ms': display_time_ms,         # Наше время отображения
            'total_time_ms': total_time_ms,             # Полное время от захвата
            'width': image_width,
            'height': image_height,
        }
        
        # ═════════════════════════════════════════════════════════════════
        # ЭМИССИЯ СИГНАЛА — единственный выход данных!
        # ═════════════════════════════════════════════════════════════════
        
        self.frame_ready.emit(frames, metrics)
    
    def _read_frames(
        self,
        id_memory: int,
        camera_robot: bool,
        processed: bool,
    ) -> List[np.ndarray]:
        """
        Чтение кадров из shared memory в зависимости от режима.
        
        Returns:
            Список numpy массивов (обычно 1 кадр)
        """
        import cv2
        
        frames = []
        
        # Режим робота — читаем из camera_data_out
        if camera_robot:
            frames_out = self._queue_manager.memory_manager.read_images(
                'camera_data_out', 0
            )
            if len(frames_out) > 0:
                # Масштабирование и обрезка для робота
                scale = 0.7
                h, w = frames_out[0].shape[:2]
                new_w, new_h = int(w * scale), int(h * scale)
                scaled = cv2.resize(frames_out[0], (new_w, new_h))
                # Обрезка по краям
                frame = scaled[:, 40:w-40]
                frames.append(frame)
            return frames
        
        # Обычный режим — читаем из camera_data или process_data
        if processed:
            # Обработанный кадр
            proc_frames = self._queue_manager.memory_manager.read_images(
                'process_data', id_memory
            )
            if proc_frames and len(proc_frames) > 0:
                frames = proc_frames
            else:
                # Fallback на оригинал
                orig_frames = self._queue_manager.memory_manager.read_images(
                    'camera_data', id_memory
                )
                frames = orig_frames
        else:
            # Оригинальный кадр
            orig_frames = self._queue_manager.memory_manager.read_images(
                'camera_data', id_memory
            )
            frames = orig_frames
        
        # Конвертация BGR → RGB если нужно
        result = []
        for frame in frames:
            if frame is None:
                continue
            
            # Копия чтобы не менять оригинал в памяти
            frame_copy = frame.copy()
            
            # Конвертация цвета если 3-канальное
            if len(frame_copy.shape) == 3 and frame_copy.shape[2] == 3:
                frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_BGR2RGB)
            
            result.append(frame_copy)
        
        return result
    
    def stop(self) -> None:
        """
        Graceful stop потока.
        Вызывается из ThreadManager или Coordinator.
        """
        # Устанавливаем флаг — run() завершится при следующей итерации
        # Не вызываем terminate() — это опасно!
        pass  # stop_event управляется снаружи
    
    def get_current_fps(self) -> float:
        """
        Текущий FPS (для информации, не для логики).
        Может быть неточным из-за threading.
        """
        return self._frame_count / max(time.time() - self._fps_start_time, 0.001)