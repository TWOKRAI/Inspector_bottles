# -*- coding: utf-8 -*-
"""
Исключения доменного слоя.

DomainError — базовый класс для всех доменных ошибок.
EntityValidationError — оборачивает pydantic.ValidationError для единообразного
стиля обработки ошибок на уровне domain.
"""

from __future__ import annotations

from pydantic import ValidationError


class DomainError(Exception):
    """Базовый класс всех доменных ошибок."""


class EntityValidationError(DomainError):
    """
    Ошибка валидации entity.

    Оборачивает pydantic.ValidationError для единообразного стиля
    обработки ошибок внутри domain (без прямой зависимости потребителей
    от pydantic в catch-блоках).
    """

    def __init__(self, message: str, cause: ValidationError | None = None) -> None:
        super().__init__(message)
        self.cause = cause

    @classmethod
    def from_pydantic(cls, exc: ValidationError) -> "EntityValidationError":
        """Создать EntityValidationError из pydantic.ValidationError."""
        return cls(str(exc), cause=exc)
