"""
core — внутренние компоненты RouterManager.

Публичный API модуля:
    RouterManager — основной класс (фасад)

Внутренние компоненты (подчёркивание = приватные, не импортировать напрямую):
    _sender.py           — AsyncSender       (PriorityQueue + sender thread)
    _receiver.py         — AsyncReceiver     (listener thread + callbacks)
    _channel_registry.py — ChannelRegistry   (thread-safe channel map + poll)
    _middleware.py       — MiddlewarePipeline (fn chain для send / receive)
"""
from .router_manager import RouterManager

__all__ = ["RouterManager"]
