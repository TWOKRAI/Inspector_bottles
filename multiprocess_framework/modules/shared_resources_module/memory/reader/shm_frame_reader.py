"""``ShmFrameReader`` — реализация `FrameReader` на multiprocessing.shared_memory (Ф7 H).

Перенос reader-side тракта из `router_module/FrameShmMiddleware` (G.3 кэш handles + G.5.b
view + G.5.c re-check) за фасад модуля памяти БЕЗ смены поведения. Импортирует
`memory.format` НАПРЯМУЮ (тот же модуль) — прежний runtime-local хак `router → shared_resources`
здесь не нужен. Синхронизация кэша — собственный lock объекта (гонка close↔read_generation
закрыта по построению: внешний код больше не трогает кэш).
"""

from __future__ import annotations

import os
import threading
from typing import Any, Optional

from ..format import read_generation, read_single_frame


class ShmFrameReader:
    """Кэш SHM-handles + чтение кадра (копия или read-only view) + post-use re-check.

    Кэш handles включён ВСЕГДА (Task 4.7b): снимает open/mmap/close на кадр. Ключ кэша —
    ``(owner, slot, idx)`` из ссылки (``key=``), а НЕ имя сегмента: realloc писателя даёт новое
    имя под тем же ключом, и старый handle уходит в отставку (``_retire_locked``), а не копится.
    Handle с ЖИВЫМ exported-view (``BufferError`` на ``close()``) не закрывается сразу — он ждёт в
    ``_retired`` (счётчик ``deferred_closes``) и закрывается на следующей отставке либо в ``close()``.
    Без ``key`` кэш ключуется именем сегмента (``(name,)``) — для читателей без кольца
    (мост Пульта: дескриптор несёт только имя); отставки по смене имени там нет, кап держит
    вызывающий через :meth:`retire`.

    Args:
        log: опц. callback для debug-строк об ошибках close().
        track: оставлять открытый сегмент под учётом ``multiprocessing.resource_tracker``
            этого процесса (дефолт ``True`` — прежнее поведение). ``False`` — для читателя ВНЕ
            дерева процессов бэкенда (Пульт, gui-service 1.3): сразу после открытия сегмент
            снимается с учёта (``resource_tracker.unregister``), иначе tracker внешнего
            процесса на его выходе делает ``unlink`` ЖИВОГО сегмента бэкенда (Python 3.12, где
            у ``SharedMemory`` ещё нет ``track=``; воспроизведено лидом 2026-09-24:
            без unregister — ``segment UNLINKED``, с ним — ``segment alive``).
            Post: при ``track=False`` ни один сегмент, открытый этим читателем, не удаляется
            при выходе процесса-читателя; ``close()`` по-прежнему только закрывает handle.
            Внутри дерева бэкенда оставлять ``True`` (дети делят tracker родителя).
    """

    def __init__(self, *, log: Optional[Any] = None, track: bool = True) -> None:
        self._track = bool(track)
        # key -> (имя сегмента, handle). dict сохраняет порядок вставки.
        self._cache: "dict[tuple, tuple[str, Any]]" = {}
        # Handles, отставленные при живом exported-view: BufferError на close() → ждут здесь.
        self._retired: "list[Any]" = []
        # Ф7 G.5 ревью-фикс 1: кэш читают ДВА потока процесса (DataReceiver на read,
        # PipelineExecutor на re-check) — lock сериализует dict + close.
        self._lock = threading.Lock()
        self._stale_drops = 0
        # Task 4.4: перезапись слота ВО ВРЕМЯ чтения по ссылке (``read_ref``) — torn.
        self._torn_reads = 0
        # Ф7 H-ревью: ошибки close() handle больше НЕ глотаются молча (принцип «терять
        # можно, молчать нельзя», ADR-SRM-012) — считаем + опц. debug-лог.
        self._close_errors = 0
        # Task 4.7b2: handles, чьё закрытие отложено из-за живого view (не ошибка).
        self._deferred_closes = 0
        self._log = log

    @property
    def stale_drops(self) -> int:
        return self._stale_drops

    @property
    def torn_reads(self) -> int:
        """Task 4.4: сколько раз слот был перезаписан ВО ВРЕМЯ чтения по ссылке (после проверки
        поколения, до конца копии/создания view) — ``read_ref`` вернул ``None``."""
        return self._torn_reads

    @property
    def close_errors(self) -> int:
        """Ф7 H-ревью: ОШИБОК close() SHM-handle (не BufferError живого view) — наблюдаемость.

        BufferError (живой exported-view) ошибкой не считается: handle откладывается
        (``deferred_closes``). Раньше любые ошибки глотались молча (`except: pass`)."""
        return self._close_errors

    @property
    def deferred_closes(self) -> int:
        """Task 4.7b2: сколько handle'ов отставлено при ЖИВОМ view (закрытие отложено).

        Растёт РОВНО раз на handle: повторная неудача закрыть тот же handle не считается. Handle
        закрывается на следующей отставке либо в ``close()``, когда view уже отпущен."""
        return self._deferred_closes

    @property
    def cache_size(self) -> int:
        """Ф7 G.7 (0.5): число открытых SHM-handle в кэше (наблюдаемость роста).

        Отставленные с живым view (``_retired``) НЕ входят: они уже не обслуживают чтение.
        Устойчивый рост = утечка handle через рестарт владельца. len(dict) атомарен в CPython."""
        return len(self._cache)

    def read_ref(self, name: str, gen: int, *, copy: bool = True, key: Optional[tuple] = None) -> Optional[Any]:
        """Task 4.4: прочитать кадр по ссылке (``ref["name"]``, ``ref["gen"]``).

        ``key`` — ``(owner, slot, idx)`` из ссылки (ключ кэша handles, Task 4.7b); ``None`` →
        ``(name,)``. Новое имя под тем же ключом отправляет старый handle в отставку.

        Поколение слота сверяется с ``gen`` ДО чтения (расхождение → ``None`` + ``stale_drops``:
        ячейка уже переписана другой записью) и ПОСЛЕ него (расхождение → ``None`` +
        ``torn_reads``: перезапись пришлась на чтение). ``copy=True`` → независимая копия;
        ``copy=False`` → read-only VIEW в слот: его слот можно перезаписать ПОСЛЕ возврата — это
        ловит ``view_valid`` (сверка с тем же ``gen``) и дверь отправки. Бросает при ошибке
        открытия сегмента и при реальной порче заголовка (стабильное поколение)."""
        from multiprocessing import shared_memory as _shm_mod

        # open + чтение под ОДНИМ lock (S2, см. _read_cached): close() другого потока не рвёт buf.
        with self._lock:
            shm = self._open_cached_locked(key if key is not None else (name,), name, _shm_mod)
            return self._read_at_generation(shm.buf, gen, copy)

    def _bump(self, attr: str) -> None:
        """``+= 1`` счётчика. ВЫЗЫВАТЬ под ``self._lock``: его бьют два потока (DataReceiver в
        ``read_ref``, PipelineExecutor в ``view_valid``), голый ``+=`` теряет обновления."""
        setattr(self, attr, getattr(self, attr) + 1)

    def _read_at_generation(self, buf: Any, gen: int, copy: bool) -> Optional[Any]:
        if read_generation(buf) != gen:
            self._bump("_stale_drops")
            return None
        frame = read_single_frame(buf, verify_seqlock=True, copy=copy)
        # read_single_frame сверяет поколение только с СОБСТВЕННЫМ первым чтением: если запись
        # целиком уложилась между нашей проверкой и его стартом, оно вернёт новый кадр — ловим тут.
        if frame is None or read_generation(buf) != gen:
            self._bump("_torn_reads")
            return None
        return frame

    def _open(self, shm_actual_name: str, shm_mod: Any) -> Any:
        """Открыть сегмент по имени; при ``track=False`` — сразу снять его с учёта
        ``resource_tracker`` этого процесса (иначе на выходе tracker удалит ЧУЖОЙ сегмент).
        Регистрация в 3.12 бывает только на POSIX — там и снимаем."""
        shm = shm_mod.SharedMemory(name=shm_actual_name, create=False)
        if not self._track and os.name == "posix":
            from multiprocessing import resource_tracker

            resource_tracker.unregister(shm._name, "shared_memory")
        return shm

    def _open_cached_locked(self, key: tuple, name: str, shm_mod: Any) -> Any:
        """Handle по ключу; новое имя под тем же ключом → старый handle в отставку. ВЫЗЫВАТЬ под
        ``self._lock`` (read_ref его уже держит — иначе close() на другом потоке порвал бы буфер
        под чтением, S2)."""
        entry = self._cache.get(key)
        if entry is not None:
            if entry[0] == name:
                return entry[1]
            self._retire_locked(key)
        shm = self._open(name, shm_mod)
        self._cache[key] = (name, shm)
        return shm

    def _retire_locked(self, key: tuple) -> None:
        """Убрать handle ключа из кэша и закрыть; при живом view — отложить (``_retired``)."""
        entry = self._cache.pop(key, None)
        self._retry_retired_locked()
        if entry is None:
            return
        if not self._try_close(entry[1], where="отставка"):
            self._retired.append(entry[1])
            self._deferred_closes += 1

    def _retry_retired_locked(self) -> None:
        """Повторить close() отложенных handle'ов; закрытые (или не поддающиеся close) — убрать."""
        if self._retired:
            self._retired = [shm for shm in self._retired if not self._try_close(shm, where="повтор отставки")]

    def retire(self, key: tuple) -> None:
        """Убрать handle ключа (кап вызывающего: мост Пульта держит LRU по имени)."""
        with self._lock:
            self._retire_locked(key)

    def _try_close(self, shm: Any, *, where: str) -> bool:
        """``False`` — handle НЕ закрыт из-за живого exported-view (``BufferError``): остаётся
        жить, повтор позже. ``True`` — закрыт либо ошибка иного рода (считается в
        ``close_errors`` + опц. debug, не глотается молча — S3; повторять смысла нет)."""
        try:
            shm.close()
        except BufferError:
            return False
        except Exception as exc:  # noqa: BLE001 — считаем + опц. debug, не роняем teardown
            self._close_errors += 1
            if self._log is not None:
                try:
                    self._log(f"ShmFrameReader: close() не удался [{where}]: {exc!r}")
                except Exception:  # noqa: BLE001
                    pass
        return True

    def view_valid(self, shm_view_name: str, gen_at_read: int, *, key: Optional[tuple] = None) -> bool:
        """Post-use re-check (G.5.c). gen<0 / handle нет / имя ключа сменилось / поколение
        разошлось → drop.

        Handle ищется по ``key`` (``None`` → ``(shm_view_name,)``); имя в кэше ≠ ``shm_view_name`` —
        handle сменился (realloc писателя) → консервативный drop."""
        # get + read_generation под ТЕМ ЖЕ lock, что open/close — иначе close() на потоке
        # DataReceiver порвал бы backing-mmap под read_generation здесь (поток Executor).
        # Счётчик — под ним же: все причины дропа бьют один и тот же ``_stale_drops`` с двух потоков.
        with self._lock:
            valid = False
            if gen_at_read >= 0:
                entry = self._cache.get(key if key is not None else (shm_view_name,))
                valid = entry is not None and entry[0] == shm_view_name and read_generation(entry[1].buf) == gen_at_read
            if not valid:
                self._stale_drops += 1
            return valid

    def close(self) -> None:
        """Закрыть все handles (teardown). Handle с живым view не закрывается — остаётся в
        ``_retired`` (``deferred_closes``) и закрывается повторным ``close()`` либо при сборке."""
        with self._lock:
            for _name, shm in self._cache.values():
                if not self._try_close(shm, where="teardown"):
                    self._retired.append(shm)
                    self._deferred_closes += 1
            self._cache.clear()
            self._retry_retired_locked()


__all__ = ["ShmFrameReader"]
