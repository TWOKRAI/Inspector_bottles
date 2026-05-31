# -*- coding: utf-8 -*-
"""
routing — контракт маршрутизации хаба (P0.2 transport-router-hub).

Декларация (без проводки в рантайм — это P1):
  - таблица ``MESSAGE_TYPE_TO_CHANNEL`` + нормализатор :func:`resolve_channel_kind`
    (см. :mod:`.routing_table`);
  - контракт address-aware канала + чистый резолвер маршрута
    (см. :mod:`.address_aware_channel`).
"""

from .address_aware_channel import RouteDecision, resolve_route, resolve_routes
from .routing_table import (
    CHANNEL_KINDS,
    COMMAND_PREFIX_TO_CHANNEL,
    DATA,
    EVENT,
    LOG,
    MESSAGE_TYPE_TO_CHANNEL,
    STATE,
    SYSTEM,
    UnknownMessageTypeError,
    channel_name,
    resolve_channel_kind,
)

__all__ = [
    # routing table
    "MESSAGE_TYPE_TO_CHANNEL",
    "COMMAND_PREFIX_TO_CHANNEL",
    "CHANNEL_KINDS",
    "SYSTEM",
    "DATA",
    "EVENT",
    "STATE",
    "LOG",
    "UnknownMessageTypeError",
    "resolve_channel_kind",
    "channel_name",
    # address-aware channel contract
    "RouteDecision",
    "resolve_route",
    "resolve_routes",
]
