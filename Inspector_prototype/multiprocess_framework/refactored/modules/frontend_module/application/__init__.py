# -*- coding: utf-8 -*-
"""
Application layer — FrontendManager, WindowManager, ThreadManager.
"""
from frontend_module.application.frontend_manager import FrontendManager
from frontend_module.application.process_attached_frontend import (
    FrontendLaunchHooks,
    run_process_attached_frontend,
)
from frontend_module.core.routed_command import RoutedCommandSender
from frontend_module.application.thread_manager import ThreadManager
from frontend_module.application.window_manager import WindowManager

__all__ = [
    "FrontendManager",
    "FrontendLaunchHooks",
    "RoutedCommandSender",
    "ThreadManager",
    "WindowManager",
    "run_process_attached_frontend",
]
