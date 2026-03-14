"""
Процесс обработки региона 2
Обертка над универсальным процессором регионов
"""
import sys
import os

# Добавляем путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Multiproccesing.Processes.process_region_processor import process_region_processor


def main(queue_manager, control_processing):
    """
    Главная функция процесса обработки региона 2
    Использует универсальный процессор с параметрами для процессора 2
    """
    process_region_processor(
        queue_manager=queue_manager,
        control_processing=control_processing,
        processor_id=2,
        input_queue=queue_manager.region_processor_queue_2
    )
