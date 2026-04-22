"""
Публичный контракт config-подмодуля.

IConfigStore — pickle-safe хранилище конфигов процессов.
Использует Any/dict для отсутствия тяжёлых зависимостей.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class IConfigStore(ABC):
    """Pickle-safe хранилище конфигов всех процессов."""

    @abstractmethod
    def store(self, name: str, config: dict) -> None:
        """Сохранить конфиг процесса."""

    @abstractmethod
    def get(self, name: str) -> Optional[dict]:
        """Получить конфиг процесса."""

    @abstractmethod
    def get_all(self) -> Dict[str, dict]:
        """Получить все конфиги."""

    @abstractmethod
    def has(self, name: str) -> bool:
        """Проверить наличие конфига."""

    @abstractmethod
    def remove(self, name: str) -> bool:
        """Удалить конфиг процесса."""


__all__ = ["IConfigStore"]
