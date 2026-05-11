"""Protocol-интерфейсы для Action-persistence.

Конкретные реализации живут в Services/sql/action_log/ — framework
работает только с этими Protocol'ами, чтобы не зависеть от sql.

См. docs/refactors/2026-05_arch_cleanup.md (Task 4.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..schemas import Action


@runtime_checkable
class IActionLogWriter(Protocol):
    """Контракт буферизованного писателя Action-лога.

    Реализация по умолчанию: Services.sql.action_log.ActionLogWriter.
    """

    def enqueue(self, action: "Action") -> None:
        """Добавить Action в буфер для последующей записи."""
        ...

    def flush(self) -> None:
        """Сбросить накопленный буфер в backend."""
        ...

    def start(self) -> None:
        """Запустить периодический flush-таймер."""
        ...

    def stop(self) -> None:
        """Остановить таймер и выполнить финальный flush."""
        ...


@runtime_checkable
class IActionLogRepository(Protocol):
    """Контракт репозитория Action-лога (CRUD над таблицей action_log)."""

    def append(self, action: "Action") -> None: ...
    def find_recent(self, n: int = 200) -> list["Action"]: ...
    def find_since(self, timestamp: float) -> list["Action"]: ...
    def count(self) -> int: ...
    def delete_before(self, timestamp: float) -> int: ...
