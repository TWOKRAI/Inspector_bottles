# -*- coding: utf-8 -*-
"""Диалоговые окна prototype: блокирующий startup-диалог, вход, подтверждение.

Реэкспорт всех публичных диалогов из единой точки:
    from multiprocess_prototype.frontend.widgets.dialogs import (
        StartupBlockingDialog,
        LoginDialog,
        ConfirmWithPasswordDialog,
    )
"""
from .startup_blocking_dialog import StartupBlockingDialog
from .login_dialog import LoginDialog
from .confirm_with_password import ConfirmWithPasswordDialog

__all__ = [
    "StartupBlockingDialog",
    "LoginDialog",
    "ConfirmWithPasswordDialog",
]
