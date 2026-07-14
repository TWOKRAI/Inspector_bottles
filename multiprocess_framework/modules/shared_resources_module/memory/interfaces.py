"""
Публичный контракт memory-подмодуля.

IMemoryManager — управление SharedMemory: owner/consumer паттерн, pickle-safe через имена.
Использует Any вместо numpy для отсутствия тяжёлых зависимостей в интерфейсном слое.

Seqlock-режим (Ф7 G.3(b), ADR-SRM-011): реализация может быть сконструирована с
``seqlock_frames=True`` (либо env ``FW_SHM_SEQLOCK``) — тогда каждый слот получает
дополнительный SLOT-header (generation-счётчик) и torn-frame (гонка writer/reader на
одном слоте без блокировок) исключается ПО ПОСТРОЕНИЮ: ``read_images`` при обнаруженной
гонке (write-in-progress ИЛИ перезапись во время копии) возвращает ``None`` — честный
drop, не порченные данные. Дефолт формата — прежний (без SLOT-header), откат = флаг off.
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
        """Создать блоки SharedMemory для процесса (owner).

        Формат слота (seqlock вкл/выкл, ADR-SRM-011) стампуется ЗДЕСЬ — единожды
        на создание — и далее самосогласован с ``write_images``/``read_images``.
        """

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

        Seqlock-слот (ADR-SRM-011): запись оборачивается протоколом generation
        (нечёт во время записи, чёт после) прозрачно для вызывающего — формат слота
        читается из его меты, не передаётся аргументом.
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

        Seqlock-слот (ADR-SRM-011): при обнаруженной гонке writer/reader (write-in-progress
        ИЛИ перезапись слота во время копии) возвращает ``None`` — честный drop торн-кадра,
        НЕ порченные данные. ``None`` в этом режиме — штатный, ожидаемый исход под
        конкуренцией, не обязательно ошибка доступа (см. также ``validate_memory_access``).
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
