# -*- coding: utf-8 -*-
"""
Контракты `storage/` — менеджер ProcessData.

`IStorageManager` — высокоуровневый менеджер компонентов в `ProcessData`
(зависит от `process_module`). Поэтому реализация в `storage/storage_manager.py`,
а не в `core/`.

Корневой [data_schema_module/interfaces.py](../interfaces.py) реэкспортирует
этот контракт для обратной совместимости (ADR-DS-005).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class IStorageManager(ABC):
    """
    Интерфейс для менеджера хранения данных компонентов в ProcessData.

    Реализация: storage/storage_manager.py.
    Зависит от process_module.ProcessData.
    """

    @abstractmethod
    def register_manager(
        self,
        manager_model: Any,
        process_name: Optional[str] = None,
    ) -> bool:
        """Зарегистрировать менеджер в ProcessData."""
        ...

    @abstractmethod
    def get_manager_model(
        self,
        manager_name: str,
        manager_type: str,
        process_name: Optional[str] = None,
    ) -> Optional[Any]:
        """Получить модель менеджера из ProcessData."""
        ...

    @abstractmethod
    def update_manager_model(
        self,
        manager_model: Any,
        process_name: Optional[str] = None,
    ) -> bool:
        """Обновить модель менеджера в ProcessData."""
        ...

    @abstractmethod
    def get_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        default: Any = None,
        process_name: Optional[str] = None,
    ) -> Any:
        """Получить конфигурацию менеджера."""
        ...

    @abstractmethod
    def update_manager_config(
        self,
        manager_type: str,
        manager_name: str,
        key: str,
        value: Any,
        process_name: Optional[str] = None,
    ) -> bool:
        """Обновить конфигурацию менеджера."""
        ...

    @abstractmethod
    def remove_manager(
        self,
        manager_name: str,
        manager_type: Optional[str] = None,
        process_name: Optional[str] = None,
    ) -> bool:
        """Удалить менеджера из ProcessData."""
        ...

    @abstractmethod
    def list_managers(
        self,
        process_name: Optional[str] = None,
        manager_type: Optional[str] = None,
    ) -> List[str]:
        """Получить список имен менеджеров."""
        ...


__all__ = [
    "IStorageManager",
]
