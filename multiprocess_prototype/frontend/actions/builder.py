"""Alias для обратной совместимости. Используй AppActionBuilder для новых домен-методов."""
from .app_action_builder import AppActionBuilder as ActionBuilder  # noqa: F401

__all__ = ["ActionBuilder"]
