# -*- coding: utf-8 -*-
"""
Application layer — FrontendManager, WindowManager, ThreadManager, Coordinator.
"""
try:
    from frontend_module.application.frontend_manager import FrontendManager
    from frontend_module.application.window_manager import WindowManager
    from frontend_module.application.thread_manager import ThreadManager
    from frontend_module.application.coordinator import ApplicationCoordinator
except ImportError:
    FrontendManager = None
    WindowManager = None
    ThreadManager = None
    ApplicationCoordinator = None

__all__ = ["FrontendManager", "WindowManager", "ThreadManager", "ApplicationCoordinator"]
