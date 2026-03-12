# -*- coding: utf-8 -*-
"""
IBufferStrategy — базовый контракт стратегии буферизации.

Реэкспортируется из interfaces.py для удобства импорта из пакета buffers.

Реализации:
    DirectBuffer      — без буферизации, прямой write() (для тестов и простых случаев)
    AsyncSenderBuffer — PriorityQueue + фоновый поток (для RouterManager)
    BatchBuffer       — deque + lock + timer flush (для LoggerManager)
"""
from ..interfaces import IBufferStrategy

__all__ = ["IBufferStrategy"]
