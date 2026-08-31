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


@runtime_checkable
class SearchableRecordSource(RecordSource, Protocol):
    """Источник, умеющий искать по СЛОВУ, а не только листать (задача 1.6).

    Отдельным протоколом, а не расширением :class:`RecordSource`, по одной
    причине: поиск — способность, которой у источника может НЕ быть. Её нет у
    сборки SQLite без FTS5 и не будет у любого источника, который однажды
    появится вместо стора. Впиши ``search`` в базовый контракт — и «умею»
    станет обязательством, которого исполнитель не может сдержать, а вкладка
    узнает об этом только на первом запросе оператора.

    ``search_available`` отвечает ДО первого запроса: панель решает, показывать
    ли живое поле ввода, в момент постройки.
    """

    def search(
        self,
        query: str,
        *,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        process: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        min_severity: Optional[int] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
    ) -> List[Dict[str, Any]]: ...

    @property
    def search_available(self) -> bool: ...


def search_unavailability(source: Optional[RecordSource]) -> Optional[str]:
    """Почему поиск недоступен у этого источника; ``None`` — доступен (1.6).

    Три разных «нельзя искать», и каждое обязано звучать по-своему — оператор,
    увидевший мёртвое поле ввода, спрашивает «почему», а не «есть ли»:

    * стор не открыт вовсе (нет файла/каталога) — вкладка и листать не может;
    * источник не умеет искать (нет метода) — например in-memory fake;
    * источник умеет, но не может здесь — сборка SQLite без FTS5, причину
      называет сам стор в ``search_unavailable_reason``.

    Проверка **duck-typing'ом, а не** ``isinstance(source, SearchableRecordSource)``:
    ``runtime_checkable`` сверяет только НАЛИЧИЕ имён, поэтому источник с методом
    ``search``, который всегда бросает, прошёл бы такую проверку — и «умею»
    осталось бы словом. Здесь спрашиваем и наличие метода, и живой ответ самого
    источника о своей готовности.
    """
    if source is None:
        return "история недоступна: стор не открыт"
    if not callable(getattr(source, "search", None)):
        return "источник записей не умеет искать (нет метода search)"
    if getattr(source, "search_available", True):
        return None
    reason = getattr(source, "search_unavailable_reason", None)
    return str(reason) if reason else "поиск недоступен (источник причину не назвал)"


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
