# -*- coding: utf-8 -*-
"""
Точка входа для процесса App Inspector.
Создаёт и запускает приложение через WindowManager.
"""
import sys
from App.Managers.window_manager import WindowManager


def create_app(queue_manager, stop_event):
    """
    Создание и запуск приложения.
    
    Args:
        queue_manager: QueueManager для межпроцессного взаимодействия
        stop_event: Event для остановки приложения
    """
    window_manager = WindowManager(queue_manager, stop_event)
    window_manager.run()
