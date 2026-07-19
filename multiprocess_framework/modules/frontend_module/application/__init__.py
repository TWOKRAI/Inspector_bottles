# -*- coding: utf-8 -*-
"""
LEGACY Gen-1 (frozen 2026-07-18) — application layer: FrontendManager,
WindowManager, ThreadManager, run_process_attached_frontend.

0 внешних потребителей (v1/v2-прототипы удалены; v3 не использует — deep-импорты
идут мимо этого поколения). Freeze, не kill (Р4 `plans/frontend-constructor/plan.md`):
пакет остаётся импортируемым, но исключён из публичного фасада `frontend_module`
(frontend-constructor Ф1, T1.2). Тесты помечены pytest-маркером `legacy_gen1`.
Инвентарь и grep-доказательства — `frontend_module/STATUS.md`.
"""

from multiprocess_framework.modules.frontend_module.application.frontend_manager import FrontendManager
from multiprocess_framework.modules.frontend_module.application.process_attached_frontend import (
    FrontendLaunchHooks,
    run_process_attached_frontend,
)
from multiprocess_framework.modules.frontend_module.core.routed_command import RoutedCommandSender
from multiprocess_framework.modules.frontend_module.application.thread_manager import ThreadManager
from multiprocess_framework.modules.frontend_module.application.window_manager import WindowManager

__all__ = [
    "FrontendManager",
    "FrontendLaunchHooks",
    "RoutedCommandSender",
    "ThreadManager",
    "WindowManager",
    "run_process_attached_frontend",
]
