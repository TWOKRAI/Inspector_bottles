"""
Процессор для конвертации изображения в grayscale
"""

import cv2
import numpy as np
from typing import Dict, Any


class GrayscaleProcessor:
    """Конвертирует изображение в grayscale (оттенки серого)"""
    
    def process(self, image: np.ndarray, params: Dict[str, Any] = None) -> np.ndarray:
        """
        Конвертирует изображение в grayscale
        
        Args:
            image: Входное изображение (может быть RGB, BGR или grayscale)
            params: Параметры (не используются)
        
        Returns:
            Изображение в grayscale формате
        """
        if params is None:
            params = {}
        
        # Если изображение уже grayscale, возвращаем как есть
        if len(image.shape) == 2:
            return image.copy()
        
        # Если изображение цветное (RGB или BGR), конвертируем в grayscale
        elif len(image.shape) == 3 and image.shape[2] == 3:
            return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        
        # Если другой формат, возвращаем как есть
        return image.copy()
    
    def get_name(self) -> str:
        return "Grayscale"
    
    def get_params_schema(self) -> list:
        return []
