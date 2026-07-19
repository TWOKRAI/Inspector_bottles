# -*- coding: utf-8 -*-
"""
LEGACY Gen-1 (frozen 2026-07-18) — LoadingWindow. 0 внешних потребителей (см.
frontend_module/STATUS.md); класс интегрирован с живым `core.app_identity`
(см. тест `test_app_identity.py::TestLoadingWindowUsesIdentity`), но сам не
подключён ни одним прикладным composition root.
"""

from .loading_window import LoadingWindow

__all__ = ["LoadingWindow"]
