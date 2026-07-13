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
from .unsaved_changes import confirm_unsaved_changes, UnsavedChoice

__all__ = [
    "StartupBlockingDialog",
    "LoginDialog",
    "ConfirmWithPasswordDialog",
    "confirm_unsaved_changes",
    "UnsavedChoice",
]
