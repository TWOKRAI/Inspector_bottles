"""Утилиты привязки виджетов к permissions через AuthState (PR3)."""
from __future__ import annotations

from .permission_gate import (
    bind_edit_permission,
    gate_edit_widgets,
    install_permission_aware_enable,
)

__all__ = [
    "bind_edit_permission",
    "gate_edit_widgets",
    "install_permission_aware_enable",
]
