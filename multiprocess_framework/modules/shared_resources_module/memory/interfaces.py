"""
Публичный контракт memory-подмодуля.

IMemoryManager — управление SharedMemory: owner/consumer паттерн, pickle-safe через имена.
Использует Any вместо numpy для отсутствия тяжёлых зависимостей в интерфейсном слое.

Seqlock (Ф7 G.3(b), ADR-SRM-011; Task 4.4 — всегда): каждый слот несёт SLOT-header с
generation-счётчиком. Запись делает поколение нечётным на время записи и чётным после; ссылка
на кадр несёт чётное поколение своей записи. Читатель сверяет его до и после копии: запись шла
или слот уже перезаписан — ``None`` и счётчик (stale/torn), а не пиксели чужой записи.
Отдельного флага seqlock больше нет (Task 4.4); ``seqlock_frames=False`` остался только для тестов формата.
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
