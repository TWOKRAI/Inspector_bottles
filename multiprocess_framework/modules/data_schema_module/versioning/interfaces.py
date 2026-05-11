# -*- coding: utf-8 -*-
"""
Контракт `versioning/` — менеджер версий моделей.

`IVersionManager` — версионирование моделей в `ProcessData` (создание версии,
rollback, diff, история). Реализация зависит от `config_module` и `ProcessData`,
поэтому конкретный класс живёт в `versioning/` и реэкспортируется через
`extensions/versioning.py` (ADR-DS-004).

Корневой [data_schema_module/interfaces.py](../interfaces.py) реэкспортирует
этот контракт для обратной совместимости (ADR-DS-005).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class IVersionManager(ABC):
    """
    Интерфейс для менеджера версий конфигов.

    Реализация живёт в extensions/versioning.py.
    Зависит от ProcessData — поэтому в extensions/.
    """

    @abstractmethod
    def create_version(
        self,
        manager_model: Any,
        comment: Optional[str] = None,
        author: Optional[str] = None,
        tags: Optional[List[str]] = None,
        process_name: Optional[str] = None,
    ) -> int:
        """Создать новую версию модели."""
        ...

    @abstractmethod
    def get_current_version(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None,
    ) -> int:
        """Получить текущую версию менеджера."""
        ...

    @abstractmethod
    def get_version(
        self,
        manager_type: str,
        manager_name: str,
        version: int,
        process_name: Optional[str] = None,
    ) -> Optional[Any]:
        """Получить модель по версии."""
        ...

    @abstractmethod
    def rollback(
        self,
        manager_type: str,
        manager_name: str,
        target_version: int,
        process_name: Optional[str] = None,
        create_new_version: bool = True,
        comment: Optional[str] = None,
    ) -> bool:
        """Откатиться к указанной версии."""
        ...

    @abstractmethod
    def get_version_history(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Получить историю версий."""
        ...

    @abstractmethod
    def compare_versions(
        self,
        manager_type: str,
        manager_name: str,
        version1: int,
        version2: int,
        process_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Сравнить две версии."""
        ...


__all__ = [
    "IVersionManager",
]
