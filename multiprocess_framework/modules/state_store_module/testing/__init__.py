"""testing — Утилиты для тестирования прикладного кода, использующего state_store_module.

Публичный API:
    InMemoryRouter — mock-реализация IRouter для unit-тестов без реального IPC.
"""
from .in_memory_router import InMemoryRouter

__all__ = ["InMemoryRouter"]
