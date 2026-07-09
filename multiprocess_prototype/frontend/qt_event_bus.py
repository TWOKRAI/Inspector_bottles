# -*- coding: utf-8 -*-
"""Шим: ``QtEventBus`` вынесен во framework (E2/Task 5.5).

Qt-мост переехал в
``multiprocess_framework.modules.frontend_module.qt_event_bridge`` (механизм
уровня 1 — cross-thread маршалинг событий, сам по себе app-agnostic). Этот модуль
сохраняет прежний путь импорта для прототипа (``app.py``,
``app_services_factory.py``, тесты) — back-compat.
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.qt_event_bridge import QtEventBus

__all__ = ["QtEventBus"]
