"""Публичный контракт reader-side кадрового тракта (Ф7 H-задача, Этап 2).

`FrameReader` — **чтение кадра из SHM у потребителя** за фасадом в модуле памяти: кэш
SHM-handles (снимает open/mmap/close на кадр), zero-copy view + post-use re-check
(G.5.c, В1-пол). До H-задачи это жило в транспортном `router_module/FrameShmMiddleware`
(~80 строк кэша+view вперемешку с транспортом + приватный `_cache_lock`, до которого
дотягивался executor). Здесь — за Protocol; транспорт держит reader через DI и делегирует.

Синхронизация кэша — **внутреннее дело reader'а** (свой lock): гонка «close() на потоке
DataReceiver под read_generation на потоке PipelineExecutor» закрыта по построению —
внешний код больше не трогает кэш напрямую. Замена на Rust-транспорт (iceoryx2, триггер
TECH_STACK §7) = новая реализация под ЭТИМ ЖЕ Protocol.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class FrameReader(Protocol):
    """Reader-side тракт кадра: кэш handles + чтение + zero-copy view + re-check.

    Реализация — per-consumer (живёт в middleware процесса-читателя). Активность кэша/
    zero-copy задаётся на конструировании (жёсткие связки G.5: zero_copy ⊃ cache ⊃
    owner_incarnation — резолвятся транспортом, reader получает уже согласованные флаги).
    """

    def read_ref(self, name: str, gen: int, *, copy: bool = True) -> Optional[Any]:
        """Task 4.4: прочитать кадр по ссылке ``(name, gen)`` — поколение слота обязано быть
        ``gen`` и ДО, и ПОСЛЕ чтения. Расхождение до → ``None`` + ``stale_drops``; во время →
        ``None`` + ``torn_reads`` (оба счётчика — свойства reader'а). ``copy=False`` + активный
        кэш → VIEW в слот. Бросает при ошибке открытия сегмента."""
        ...

    def view_valid(self, shm_view_name: str, gen_at_read: int) -> bool:
        """Post-use re-check (G.5.c): жив ли ещё zero-copy view (слот не перезаписан).

        Сверяет ТЕКУЩЕЕ поколение слота с поколением на момент чтения. Совпало → view
        валиден. Разошлось / handle эвиктнут / gen_at_read<0 → drop (счётчик
        ``stale_drops``), НЕ порча. Использует тот же кэшированный handle (без нового open).
        """
        ...

    def close(self) -> None:
        """Закрыть все кэшированные SHM-handles (teardown wire/процесса)."""
        ...

    @property
    def stale_drops(self) -> int:
        """Сколько чтений/view отброшено по расхождению поколения: ссылка на перезаписанную
        ячейку (Task 4.4) или view, пережитый перезаписью (post-use re-check)."""
        ...

    @property
    def torn_reads(self) -> int:
        """Task 4.4: сколько чтений по ссылке порвала перезапись слота во время копии."""
        ...


__all__ = ["FrameReader"]
