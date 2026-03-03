# -*- coding: utf-8 -*-
"""
Каналы для RouterManager.
Часть multiprocess_framework — все каналы живут здесь.
"""
from .queue_channel import QueueChannel
from .fanout_channel import FanoutChannel
from ..channel import MessageChannel

__all__ = ['MessageChannel', 'QueueChannel', 'FanoutChannel']
