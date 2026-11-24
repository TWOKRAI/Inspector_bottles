# -*- coding: utf-8 -*-
"""Кольцо кадров по времени и формат сегмента; сюда — менять вытеснение, закрепление, формат записи

Purpose: экспорт `TimeRing` (кольцо в RAM) и `read_segment` (читатель блока JPEG + индекса).
"""

from Services.frame_buffer.segment import read_segment
from Services.frame_buffer.time_ring import TimeRing

__all__ = ["TimeRing", "read_segment"]
