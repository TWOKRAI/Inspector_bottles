"""
Публичные контракты модуля fps_module.

Не thread-safe — использовать только из одного потока (например, потока рендеринга).
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class FPSProvider(Protocol):
    """Контракт счётчика FPS. Вызывать update() каждый кадр."""

    def update(self) -> float:
        """Инкремент. Returns: FPS при обновлении, иначе 0.0"""
        ...

    def get_fps(self) -> float:
        """Текущий FPS."""
        ...

    def reset(self) -> None:
        """Сброс состояния."""
        ...
