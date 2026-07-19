"""interfaces.py — публичные контракты telemetry_readmodel_module (правило №2).

``ITelemetryReadModel`` — контракт локальной read-model телеметрии: снимок
проекции состояния + история по ключевым метрикам, наполняемые потоком уже
разобранных дельт. Транспорт-агностичен (см. :meth:`ingest`); реализация —
:class:`TelemetryReadModel`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ITelemetryReadModel(Protocol):
    """Контракт read-model телеметрии (Qt-free, envelope-agnostic).

    Наполняется потоком дельт через :meth:`ingest`; читается локально —
    ``get``/``snapshot``/``history`` не делают IPC и не создают подписок.
    """

    def prime(self, cache: dict[str, Any]) -> None:
        """Залить первичный снимок ``{path: value}`` (без истории для нечисловых)."""
        ...

    def ingest(self, path: str, value: Any, *, deleted: bool = False) -> None:
        """Внести одну разобранную дельту: обновить снимок и историю; deleted → удалить путь."""
        ...

    def get(self, path: str, default: Any = None) -> Any:
        """Текущее значение по пути (или default)."""
        ...

    def snapshot(self, prefix: str) -> dict[str, Any]:
        """Снимок поддерева по префиксу (граница — точка-разделитель); пустой prefix → весь снимок."""
        ...

    def history(self, path: str, since: float | None = None) -> list[tuple[float, Any]]:
        """Кольцевой буфер ``(ts, value)`` метрики; since — нижняя граница ts (wall-clock)."""
        ...

    def export_history(self) -> dict[str, list[tuple[float, float]]]:
        """Снимок всех кольцевых буферов истории (``path → [(ts, value), ...]``), JSON-safe."""
        ...

    def import_history(self, data: dict[str, list[tuple[float, float]]]) -> None:
        """Восстановить буферы истории из export_history-снимка (записанные ts, maxlen соблюдён)."""
        ...


__all__ = ["ITelemetryReadModel"]
