# -*- coding: utf-8 -*-
"""Шим: ``resolve_plugin_register`` вынесен во framework (E1/Task 5.4).

Чистая функция переехала в
``multiprocess_framework.modules.frontend_module.bridge.plugin_register_resolver``.
Этот модуль сохраняет прежний путь импорта для прототипа (``app.py`` и тесты) —
back-compat, обратный импорт направления app → framework (разрешён).
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.bridge.plugin_register_resolver import (
    resolve_plugin_register,
)

__all__ = ["resolve_plugin_register"]
