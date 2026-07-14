"""``ShmFrameReader`` — реализация `FrameReader` на multiprocessing.shared_memory (Ф7 H).

Перенос reader-side тракта из `router_module/FrameShmMiddleware` (G.3 кэш handles + G.5.b
zero-copy + G.5.c re-check) за фасад модуля памяти БЕЗ смены поведения. Импортирует
`memory.format` НАПРЯМУЮ (тот же модуль) — прежний runtime-local хак `router → shared_resources`
здесь не нужен. Синхронизация кэша — собственный lock объекта (гонка close↔read_generation
закрыта по построению: внешний код больше не трогает кэш).
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from ..format import read_generation, read_single_frame


class ShmFrameReader:
    """Кэш SHM-handles + чтение кадра + zero-copy view + post-use re-check.

    Args:
        cache_enabled: переиспользовать handles (снимает open/mmap/close на кадр).
        zero_copy: отдавать VIEW в слот вместо копии (требует cache_enabled — гейтит
            транспорт; под zero-copy эвикция с close() ОТКЛЮЧЕНА, иначе view повис бы).
        cap: LRU-кэп кэша handles (эвикция самого старого при переполнении, если не zero-copy).
    """

    def __init__(self, *, cache_enabled: bool, zero_copy: bool, cap: int) -> None:
        self._cache_enabled = bool(cache_enabled)
        self._zero_copy = bool(zero_copy)
        self._cap = max(1, int(cap))
        # dict сохраняет порядок вставки → FIFO ~ LRU для стабильного потока имён.
        self._cache: "dict[str, Any]" = {}
        # Ф7 G.5 ревью-фикс 1: кэш читают ДВА потока процесса (DataReceiver на read,
        # PipelineExecutor на re-check) — lock сериализует dict + close.
        self._lock = threading.Lock()
        self._stale_drops = 0

    @property
    def stale_drops(self) -> int:
        return self._stale_drops

    def read_frame(
        self,
        shm_actual_name: str,
        seqlock: bool = False,
        *,
        copy: bool = True,
        view_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        from multiprocessing import shared_memory as _shm_mod

        if self._cache_enabled:
            shm = self._open_cached(shm_actual_name, _shm_mod)
            frame = read_single_frame(shm.buf, verify_seqlock=seqlock, copy=copy)
            if frame is not None and not copy and view_meta is not None:
                # Мета для G.5.c: поколение на момент чтения (сверка ПОСЛЕ использования
                # view). Без seqlock поколения нет → -1 (re-check неактивен).
                view_meta["_frame_is_view"] = True
                view_meta["_shm_view_name"] = shm_actual_name
                view_meta["_shm_view_generation"] = read_generation(shm.buf) if seqlock else -1
            return frame

        # Без кэша сегмент закрывается сразу → view повис бы: копия обязательна.
        shm = _shm_mod.SharedMemory(name=shm_actual_name, create=False)
        try:
            return read_single_frame(shm.buf, verify_seqlock=seqlock, copy=True)
        finally:
            shm.close()

    def _open_cached(self, shm_actual_name: str, shm_mod: Any) -> Any:
        """Открыть SharedMemory с LRU-кэшем (инвалидация по смене имени)."""
        with self._lock:
            shm = self._cache.pop(shm_actual_name, None)
            if shm is not None:
                self._cache[shm_actual_name] = shm  # move-to-end (LRU)
                return shm
            shm = shm_mod.SharedMemory(name=shm_actual_name, create=False)
            self._cache[shm_actual_name] = shm
            # Ф7 G.5 ревью-фикс 1: эвикция с close() — ТОЛЬКО без zero-copy. Под zero-copy
            # view живёт ПОСЛЕ чтения (до конца обработки) и re-check читает его на другом
            # потоке → close() эвиктнутого handle = dangling/BufferError. Держим сегменты
            # открытыми до teardown (их немного — per-camera).
            if not self._zero_copy and len(self._cache) > self._cap:
                old_name = next(iter(self._cache))
                old_shm = self._cache.pop(old_name)
                try:
                    old_shm.close()
                except Exception:
                    pass
            return shm

    def view_valid(self, shm_view_name: str, gen_at_read: int) -> bool:
        """Post-use re-check (G.5.c). gen<0 / handle нет / поколение разошлось → drop."""
        if gen_at_read < 0:
            self._stale_drops += 1
            return False
        # get + read_generation под ТЕМ ЖЕ lock, что open/close — иначе close() на потоке
        # DataReceiver порвал бы backing-mmap под read_generation здесь (поток Executor).
        with self._lock:
            shm = self._cache.get(shm_view_name)
            if shm is None:
                # handle эвиктнут/сменился → сегмент мог закрыться → консервативный drop.
                self._stale_drops += 1
                return False
            valid = read_generation(shm.buf) == gen_at_read
        if valid:
            return True
        self._stale_drops += 1
        return False

    def close(self) -> None:
        with self._lock:
            for shm in self._cache.values():
                try:
                    shm.close()
                except Exception:
                    pass
            self._cache.clear()


__all__ = ["ShmFrameReader"]
