"""
Публичный контракт memory-подмодуля.

IMemoryManager — управление SharedMemory: owner/consumer паттерн, pickle-safe через имена.
Использует Any вместо numpy для отсутствия тяжёлых зависимостей в интерфейсном слое.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class IMemoryManager(ABC):
    """Управление SharedMemory: owner/consumer паттерн, pickle-safe через имена."""

    @abstractmethod
    def create_memory_dict(
        self,
        process_name: str,
        memory_names: Dict[str, tuple],
        coll: int,
    ) -> bool:
        """Создать блоки SharedMemory для процесса (owner)."""

    @abstractmethod
    def get_memory_data(
        self,
        process_name: str,
        memory_name: str,
    ) -> Optional[Dict]:
        """Получить метаданные блока памяти."""

    @abstractmethod
    def write_images(
        self,
        process_name: str,
        memory_name: str,
        images: List[Any],
        index: int,
        pack_fast: bool = True,
    ) -> Optional[str]:
        """
        Записать изображения в SharedMemory.

        pack_fast: True — np.copyto (быстрее). False — tobytes (legacy, совместимость).
        """

    @abstractmethod
    def read_images(
        self,
        process_name: str,
        memory_name: str,
        index: int,
        n: int = -1,
        copy: bool = True,
    ) -> Optional[List[Any]]:
        """
        Прочитать изображения из SharedMemory.

        copy: True — копии (безопасно). False — view (быстрее, использовать до следующей записи).
        """

    @abstractmethod
    def release_memory(self, process_name: str, memory_name: str, index: int) -> None:
        """Освободить слот памяти."""

    @abstractmethod
    def close_memory(self, process_name: str, memory_name: str) -> None:
        """Закрыть и очистить блок памяти."""

    @abstractmethod
    def release_process_memory(self, process_name: str) -> None:
        """Полный teardown SHM процесса (hot-swap): закрыть все блоки + снять с PSR."""

    @abstractmethod
    def reinitialize_handles(self) -> bool:
        """Открыть SharedMemory по именам после unpickle (consumer)."""


__all__ = ["IMemoryManager"]
