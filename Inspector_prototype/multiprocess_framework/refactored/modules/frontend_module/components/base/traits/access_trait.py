# -*- coding: utf-8 -*-
"""
AccessTrait — проверка прав доступа.
"""
from __future__ import annotations


class AccessTrait:
    """Трейт: проверка прав доступа для редактирования."""

    def __init__(self, required_level: int) -> None:
        self._required = required_level
        self._current = 0

    def update(self, current_level: int) -> None:
        self._current = current_level

    def set_required_level(self, required_level: int) -> None:
        """Обновить требуемый уровень (например, после `SchemaTrait.refresh()`)."""
        self._required = required_level

    def can_modify(self) -> bool:
        return self._current >= self._required
