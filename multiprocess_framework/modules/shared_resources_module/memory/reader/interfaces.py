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

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class FrameReader(Protocol):
    """Reader-side тракт кадра: кэш handles + чтение + zero-copy view + re-check.

    Реализация — per-consumer (живёт в middleware процесса-читателя). Активность кэша/
    zero-copy задаётся на конструировании (жёсткие связки G.5: zero_copy ⊃ cache ⊃
    owner_incarnation — резолвятся транспортом, reader получает уже согласованные флаги).
    """

    def read_frame(
        self,
        shm_actual_name: str,
        seqlock: bool = False,
        *,
        copy: bool = True,
        view_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Прочитать ОДИН кадр из SHM по фактическому OS-имени (cross-process).

        При активном кэше handle переиспользуется; иначе open/close на кадр (копия
        форсируется — сегмент закрывается сразу, view повис бы). ``copy=False`` +
        активный кэш → VIEW в слот, и в ``view_meta`` кладётся мета для post-use re-check
        (``_frame_is_view``/``_shm_view_name``/``_shm_view_generation``). ``None`` —
        torn/in-progress под seqlock (штатный drop). Бросает при ошибке открытия.
        """
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
        """Сколько zero-copy view дропнуто post-use re-check'ом (наблюдаемость)."""
        ...


__all__ = ["FrameReader"]
