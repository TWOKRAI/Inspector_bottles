# -*- coding: utf-8 -*-
"""
domain/event_bus.py — тонкий re-export-шим (carve-out 2026-06-18).

Реальная generic-реализация ``EventBus`` вынесена во framework
(``multiprocess_framework.modules.event_module``, правило framework-first). Прототип —
тонкий потребитель: импорты ``from ...domain.event_bus import EventBus`` сохраняются без
изменений у всех потребителей (включая ``frontend/qt_event_bus.py``).

Pure Python, 0 Qt (Qt-обёртка — ``frontend/qt_event_bus.py``).
Refs: docs/audits/2026-06-18_command-undo-system.md (правило framework-first), ADR EVT-001.
"""

from __future__ import annotations

from multiprocess_framework.modules.event_module import ErrorHandler, EventBus

__all__ = ["EventBus", "ErrorHandler"]
