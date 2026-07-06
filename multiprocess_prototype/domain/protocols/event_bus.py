# -*- coding: utf-8 -*-
"""
domain/protocols/event_bus.py — тонкий re-export-шим (carve-out 2026-06-18).

Контракты ``EventBusProtocol`` / ``Subscription`` вынесены во framework
(``multiprocess_framework.modules.event_module``). Прототип — тонкий потребитель:
импорты ``from ...domain.protocols.event_bus import EventBusProtocol`` сохраняются.

Refs: docs/audits/2026-06-18_command-undo-system.md, ADR EVT-001.
"""

from __future__ import annotations

from multiprocess_framework.modules.event_module import EventBusProtocol, Subscription

__all__ = ["Subscription", "EventBusProtocol"]
