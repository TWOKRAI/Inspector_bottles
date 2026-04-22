"""
Процессор для конвертации изображения в BGR
"""

import cv2
import numpy as np
from typing import Dict, Any


class BGRProcessor:
    """Конвертирует изображение в BGR формат"""
    
    def process(self, image: np.ndarray, params: Dict[str, Any] = None) -> np.ndarray:
        """
        Конвертирует изображение в BGR
        
        Args:
            image: Входное изображение (может быть RGB, BGR или grayscale)
            params: Параметры (не используются)
        
        Returns:
            Изображение в BGR формате
        """
        if params is None:
            params = {}
        
        # Если изображение уже в RGB (3 канала), конвертируем в BGR
        if len(image.shape) == 3 and image.shape[2] == 3:
            # Изображение приходит в RGB формате из process_region_processor
            # Конвертируем в BGR
            return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # Если изображение grayscale, конвертируем в BGR
        elif len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        
        # Если уже BGR или другой формат, возвращаем как есть
        return image.copy()
    
    def get_name(self) -> str:
        return "BGR"
    
    def get_params_schema(self) -> list:
        return []
