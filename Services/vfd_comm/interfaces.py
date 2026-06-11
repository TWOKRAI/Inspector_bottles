"""Публичные контракты vfd_comm (Protocol, structural subtyping)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from Services.vfd_comm.core.datatypes import VFDStatus


@runtime_checkable
class VfdClientProtocol(Protocol):
    """Контракт клиента ПЧ — то, что видят плагины и UI."""

    @property
    def is_connected(self) -> bool:
        """Жив ли транспорт."""
        ...

    def run(self, freq_hz: float | None = None, reverse: bool = False) -> bool:
        """Запустить вращение."""
        ...

    def set_freq(self, freq_hz: float) -> bool:
        """Сменить частоту на ходу."""
        ...

    def stop(self) -> bool:
        """Остановить."""
        ...

    def reset_fault(self) -> bool:
        """Сбросить аварию."""
        ...

    def read_status(self) -> VFDStatus:
        """Прочитать статус как есть."""
        ...

    def poll(self) -> VFDStatus:
        """Пульс-опрос (мост): обновить зеркало и прочитать."""
        ...
