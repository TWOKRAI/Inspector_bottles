# -*- coding: utf-8 -*-
"""Fencing-token (Ф4.2): штамп конверта + drop stale на приёме.

Публичный API — см. :mod:`.token`. Проводка в роутер (флаг ``FW_FENCE``,
провайдеры epoch/incarnation из PSR) — забота композиции процесса.
"""
from .token import (
    FENCE_KEY,
    DropHook,
    FenceProvider,
    IncarnationProvider,
    MiddlewareFn,
    is_data_plane,
    make_fence_filter_middleware,
    make_fence_stamp_middleware,
    read_fence,
)

__all__ = [
    "FENCE_KEY",
    "FenceProvider",
    "IncarnationProvider",
    "MiddlewareFn",
    "DropHook",
    "is_data_plane",
    "read_fence",
    "make_fence_stamp_middleware",
    "make_fence_filter_middleware",
]
