"""
Процесс обработки региона 1
Обертка над универсальным процессором регионов
"""
import sys
import os

# Добавляем путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Multiproccesing.Processes.process_region_processor import process_region_processor


def main(queue_manager, control_processing):
    """
    Главная функция процесса обработки региона 1
    Использует универсальный процессор с параметрами для процессора 1
    """
    process_region_processor(
        queue_manager=queue_manager,
        control_processing=control_processing,
        processor_id=1,
        input_queue=queue_manager.region_processor_queue_1
    )
