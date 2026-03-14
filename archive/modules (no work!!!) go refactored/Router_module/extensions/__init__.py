# -*- coding: utf-8 -*-
"""
Расширения RouterManager (Content-Based Router и др.).
Часть multiprocess_framework.
"""
from .register_routing import (
    register_register_routing,
    create_register_update_message,
    get_routing_metadata,
)

__all__ = [
    'register_register_routing',
    'create_register_update_message',
    'get_routing_metadata',
]
