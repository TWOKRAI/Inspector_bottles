# -*- coding: utf-8 -*-
"""
RecordSource — контракт источника записей наблюдаемости для вкладок (Ф5.19).

Целую историю вкладки Логи/Ошибки/Статистика читают пагинацией из
persistent-стора (Ф5.20a) — общий SQLite-файл ``observability.db``, куда пишут
ВСЕ backend-процессы (WAL); GUI открывает его на чтение. Живой хвост приходит
отдельным каналом (Ф5.20b) и НЕ через этот источник.

Виджет зависит от узкого Protocol'а (не от ObservabilityStore напрямую) —
presenter/тесты подставляют fake-источник без SQLite. ObservabilityStore
структурно удовлетворяет контракту.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class RecordSource(Protocol):
    """Пагинированный источник записей (kind: log/error/stats)."""

    def list_records(
        self,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
    ) -> List[Dict[str, Any]]: ...

    def count(self, kind: Optional[str] = None) -> int: ...

    def clear(self, kind: Optional[str] = None) -> int: ...


def open_default_source() -> Optional[RecordSource]:
    """Открыть общий ObservabilityStore на чтение (``<log_dir>/observability.db``).

    Возвращает None, если стор недоступен (нет файла/каталога) — вкладки тогда
    показывают пустую историю, но не падают. Живой хвост работает независимо.
    """
    try:
        from multiprocess_framework.modules.channel_routing_module.observability import (
            ObservabilityStore,
            resolve_default_db_path,
        )

        return ObservabilityStore(resolve_default_db_path())
    except Exception:  # noqa: BLE001 — отсутствие стора не должно ронять GUI
        return None
