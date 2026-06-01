# -*- coding: utf-8 -*-
"""
builders — чистые хелперы построения dict-сообщений протокола.

Единый источник правды формы команд: и GUI (`CommandSender`), и внешний driver
(backend_ctl) строят сообщения ОДНИМИ функциями, чтобы «GUI и driver шлют одинаковое»
гарантировалось кодом, а не дисциплиной. Driver дополнительно задаёт reply-поля
(`request_id`/`reply_to`) для request-response (P0.5); GUI их опускает (fire-and-forget).
"""

from .command_envelopes import (
    build_command_message,
    build_system_command_message,
)

__all__ = [
    "build_command_message",
    "build_system_command_message",
]
