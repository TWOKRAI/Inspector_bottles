"""
Процессы шаблонного приложения.

Демонстрируют использование ProcessModule для создания различных типов процессов.
"""

from .vision_process import VisionProcess
from .ai_process import AIProcess
from .db_process import DBProcess
from .ui_process import UIProcess

__all__ = [
    'VisionProcess',
    'AIProcess',
    'DBProcess',
    'UIProcess'
]

