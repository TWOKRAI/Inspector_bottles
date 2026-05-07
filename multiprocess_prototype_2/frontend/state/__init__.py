"""frontend/state — Подписки виджетов на пути StateStore (Phase 10A).

Публичный API:
    match_glob(pattern, path) → bool  — glob-матчинг сегментов пути
    GuiStateBindings            — менеджер реактивных подписок
    BindingHandle               — дескриптор одной подписки
"""
from .glob_match import match_glob
from .bindings import BindingHandle, GuiStateBindings

__all__ = [
    "match_glob",
    "GuiStateBindings",
    "BindingHandle",
]
