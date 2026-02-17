"""
Процессоры для обработки регионов.
Отдельные классы для базовых преобразований цветового пространства.
"""

from .rgb_processor import RGBProcessor
from .bgr_processor import BGRProcessor
from .grayscale_processor import GrayscaleProcessor

# Реестр процессоров регионов
REGION_PROCESSORS = {
    'rgb': RGBProcessor,
    'bgr': BGRProcessor,
    'grayscale': GrayscaleProcessor,
}


def get_processor(processor_id: str):
    """Получить класс процессора по ID"""
    return REGION_PROCESSORS.get(processor_id)


def process_region(image, processor_id: str, params: dict = None):
    """
    Обработать регион используя указанный процессор
    
    Args:
        image: numpy array изображения
        processor_id: ID процессора ('rgb', 'bgr', 'grayscale')
        params: дополнительные параметры (опционально)
    
    Returns:
        Обработанное изображение
    """
    processor_class = get_processor(processor_id)
    if processor_class is None:
        print(f"Unknown processor_id: {processor_id}, returning original image")
        return image.copy()
    
    processor = processor_class()
    if params is None:
        params = {}
    return processor.process(image, params)
