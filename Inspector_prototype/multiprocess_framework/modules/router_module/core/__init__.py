"""
core — внутренние компоненты RouterManager.

Публичный API модуля:
    RouterManager — основной класс (фасад)

Внутренние компоненты (подчёркивание = приватные, не импортировать напрямую):
    _sender.py           — AsyncSender       (PriorityQueue + sender thread)
    _receiver.py         — AsyncReceiver     (listener thread + callbacks)
    _middleware.py       — MiddlewarePipeline (fn chain для send / receive)

Реестр каналов: self._channel_registry наследуется от ChannelRoutingManager (CRM).
"""
from .router_manager import RouterManager

__all__ = ["RouterManager"]
