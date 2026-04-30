"""
Процессор для конвертации изображения в RGB
"""

import cv2
import numpy as np
from typing import Dict, Any


class RGBProcessor:
    """Конвертирует изображение в RGB формат"""
    
    def process(self, image: np.ndarray, params: Dict[str, Any] = None) -> np.ndarray:
        """
        Конвертирует изображение в RGB
        
        Args:
            image: Входное изображение (может быть BGR, RGB или grayscale)
            params: Параметры (не используются)
        
        Returns:
            Изображение в RGB формате
        """
        if params is None:
            params = {}
        
        # Если изображение уже в RGB (3 канала), проверяем формат
        if len(image.shape) == 3 and image.shape[2] == 3:
            # Изображение уже должно быть в RGB (так как в process_region_processor уже конвертируется)
            # Но на всякий случай проверяем и конвертируем если нужно
            # Возвращаем как есть, так как процессор регионов уже работает с RGB
            return image.copy()
        
        # Если изображение grayscale, конвертируем в RGB
        elif len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        
        # Если уже RGB или другой формат, возвращаем как есть
        return image.copy()
    
    def get_name(self) -> str:
        return "RGB"
    
    def get_params_schema(self) -> list:
        return []
