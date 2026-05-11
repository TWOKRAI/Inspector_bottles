# -*- coding: utf-8 -*-
"""
AccessTrait — проверка прав доступа.

PR1-Group-C: расширен двухосевой моделью (view + edit) с именованными permissions.
Legacy API (required_level=, update(int)) сохранён через DeprecationWarning.

Coherence invariant: edit ⇒ view
  Если can_view() == False → can_modify() тоже False.
"""
from __future__ import annotations

import warnings

from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext


class AccessTrait:
    """
    Трейт: двухосевая проверка прав доступа (view + edit).

    Параметры конструктора:
    - legacy_required_level  — числовой уровень для legacy-сравнения (ctx.level >= N)
    - required_view_permission — если задан, ctx.has_permission(...) для видимости
    - required_edit_permission — если задан, ctx.has_permission(...) для редактирования
    - required_level         — устаревший alias для legacy_required_level; DeprecationWarning

    Позиционный первый аргумент принимается как legacy_required_level
    (сохраняет совместимость с вызовами AccessTrait(5)).
    """

    def __init__(
        self,
        legacy_required_level: int = 0,
        required_view_permission: str | None = None,
        required_edit_permission: str | None = None,
        *,
        required_level: int | None = None,
    ) -> None:
        # Поддержка устаревшего kwargs required_level=
        if required_level is not None:
            warnings.warn(
                "AccessTrait(required_level=...) is deprecated, "
                "use legacy_required_level= instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            legacy_required_level = required_level

        self._required: int = legacy_required_level
        self._view_permission: str | None = required_view_permission
        self._edit_permission: str | None = required_edit_permission
        # Текущий контекст доступа (дефолт — нулевой)
        self._ctx: AccessContext = AccessContext(level=0)

    # ------------------------------------------------------------------
    # Обновление контекста
    # ------------------------------------------------------------------

    def update(self, ctx_or_level: AccessContext | int) -> None:
        """
        Обновить текущий контекст доступа.

        Принимает AccessContext (новый путь) или int (legacy путь + DeprecationWarning).
        """
        if isinstance(ctx_or_level, int):
            warnings.warn(
                "AccessTrait.update(int) is deprecated, "
                "pass AccessContext instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            # Создаём минимальный контекст: сохраняем bypass_readonly из текущего ctx
            self._ctx = AccessContext(
                level=ctx_or_level,
                bypass_readonly=self._ctx.bypass_readonly,
                show_hidden=self._ctx.show_hidden,
            )
        else:
            self._ctx = ctx_or_level

    def set_required_level(self, required_level: int) -> None:
        """Обновить требуемый числовой уровень (например, после SchemaTrait.refresh())."""
        self._required = required_level

    # ------------------------------------------------------------------
    # Проверки прав
    # ------------------------------------------------------------------

    def can_view(self) -> bool:
        """
        Может ли пользователь видеть элемент?

        Если required_view_permission задан → ctx.has_permission(name).
        Если не задан → True (нет ограничения по просмотру).
        """
        if self._view_permission is not None:
            return self._ctx.has_permission(self._view_permission)
        return True

    def can_modify(self) -> bool:
        """
        Может ли пользователь редактировать элемент?

        Coherence invariant: edit ⇒ view — если can_view() == False, возвращаем False.

        Если required_edit_permission задан → ctx.has_permission(name).
        Иначе legacy: ctx.level >= legacy_required_level ИЛИ ctx.bypass_readonly.
        """
        # Coherence: нет view → нет edit
        if not self.can_view():
            return False

        if self._edit_permission is not None:
            return self._ctx.has_permission(self._edit_permission)

        # Legacy fallback
        return self._ctx.level >= self._required or self._ctx.bypass_readonly
