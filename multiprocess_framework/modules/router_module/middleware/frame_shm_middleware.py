# -*- coding: utf-8 -*-
"""FrameShmMiddleware — единый middleware «frame ↔ SHM ref» (P3.1.1, ADR-COMM-003).

Слияние двух ранее дублировавшихся реализаций (§5.2 аудита) + Ф7 G.3 (ADR-RTR-009):
- generic data-pipeline (`process_module/generic`): `strip_and_write`/`restore_frame`
  — lazy-allocation, round-robin ring, pickle-fallback при сбое SHM-write;
- router middleware (`router_module/middleware`): `on_send`/`on_receive`
  — middleware-протокол RouterManager (`add_send_middleware`/`add_receive_middleware`).

**Ф7 G.3 (a) — одно ядро записи.** `strip_and_write` и `on_send` больше не имеют
раздельной логики выбора слота: обе делегируют в `_write_frame_into_slot` (lazy-alloc +
realloc-on-grow + round-robin — канон generic). Прежний `find_free_index`-путь `on_send`
снят (он всегда возвращал 0 — `index_usage` никем не инкрементился). Различие путей —
только адаптер: откуда берётся frame и куда кладутся координаты.

**Ф7 G.3 (b) — seqlock.** Слот SHM может быть в seqlock-формате (ADR-SRM-011). Task 4.4: заголовок
seqlock у слота ВСЕГДА (флага нет); поколение записи едет в ссылке (`gen`), cross-process reader
(`FrameReader.read_ref`) сверяет его до и после чтения и дропает stale/torn кадр.

**Ф7 G.3 (d) — громкий pickle-fallback.** Сбой SHM-write (mm есть, но запись не удалась)
→ кадр уходит pickle-через-Queue (×3 латентность). Раньше — молча. Теперь: счётчик
`frame_pickle_fallbacks` (агрегируется в `RouterManager.get_stats`) + throttled WARNING.

**Ф7 G.3 (кэш handles) / H-задача Этап 2.** Cross-process raw-чтение открывало SharedMemory
на каждый кадр (open/mmap/close + resource_tracker). Кэш handles + zero-copy view + post-use
re-check вынесены за фасад `FrameReader` (модуль памяти); транспорт держит reader через DI и
делегирует (`read_ref`/`view_valid`/`close_handle_cache`), синхронизация — внутри reader'а.

**Ф7 G.4.b — глубина кольца per-camera (B-8).** `coll` (число SHM-слотов round-robin)
теперь настраивается на КОНКРЕТНУЮ камеру: явный `coll` из рецепта/wire (`buffer_slots`,
раньше игнорировался) > QoS-профиль data при `FW_QOS_PROFILES` (history_depth) > 3.
Каждый source-процесс = свой `owner` = своё независимое кольцо (изоляция цепочек камер:
замедление/дроп одной камеры не трогает слоты другой). Владение слотом до release
последним читателем (fan-out refcount, reclaim-on-death) — G.5 (нагружено только с
zero-copy; header G.3 уже несёт state/refcount).

Claim Check: пиксели (numpy) едут в OS SHM, по очереди — только координаты (shm_ref).
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

# Размер LRU-кэша SHM-handles читателя (обычно 1–3 живых имени; запас на realloc/switch).
_HANDLE_CACHE_CAP = 8
# Throttle громкого WARNING про pickle-fallback (счётчик — всегда, лог — раз в N кадров).
_PICKLE_WARN_EVERY = 300
# Throttle лога «frame не восстановлен» (штатный drop после G.7 — не ERROR на каждый кадр).
_RESTORE_FAIL_WARN_EVERY = 300

# Task 4.1 (transport-single-policy, C1-C2): порог claim check по размеру. Любой ключ
# ВЕРХНЕГО уровня ``msg["data"]`` (кроме ``frame`` — тот ссылкой всегда) с ndarray
# ``nbytes >= CLAIM_CHECK_MIN_NBYTES`` едет ссылкой на SHM; мельче — inline, не трогается.
CLAIM_CHECK_MIN_NBYTES = 8192
# Task 4.4: ЕДИНЫЙ формат ссылки для КАЖДОГО крупного массива, включая ``frame``:
# ``data["_shm_refs"][key] = {"owner", "slot", "idx", "gen", "name"}`` — ровно пять полей.
# ``gen`` — ЧЁТНОЕ поколение слота, которое произвела ЭТА запись: ссылка указывает на КАДР,
# а не на ячейку кольца. Читатель сверяет поколение слота с ``gen`` (перезаписанная ячейка →
# ``None`` + stale, а не чужие пиксели).
SHM_REFS_KEY = "_shm_refs"
# Ключ кадра: ссылка на него лежит там же, где и остальные (``_shm_refs["frame"]``).
FRAME_KEY = "frame"
# Ключи item'а, живущие ТОЛЬКО внутри процесса (на провод не уходят, send-дверь их снимает):
#  * ``_shm_views`` — список входных ссылок, восстановленных zero-copy view (для post-use
#    re-check в executor и в двери отправки);
#  * ``_shm_dropped`` — метка «вход был перезаписан, пока копировали»: item и все его fan-out
#    повторы дропаются.
SHM_VIEWS_KEY = "_shm_views"
SHM_DROPPED_KEY = "_shm_dropped"


def _is_large_array(value: Any) -> bool:
    """Голый числовой ndarray нативного порядка байт, ``ndim`` 2–3, ``nbytes >=
    CLAIM_CHECK_MIN_NBYTES`` (C1/C2).

    4.1-fix (ревью 4.1, находка 1 + повторное ревью): SHM-слот хранит изображение-подобный
    массив ``(H, W[, C])`` числового dtype, а в заголовке — только ``dtype.char``. Поэтому
    через слот не восстанавливаются: строки/bytes/object/void/``datetime64``/``timedelta64``
    (молча ``None`` / dtype без единицы / fallback), big-endian (порядок байт теряется —
    приходят неверные числа), подкласс ndarray (``MaskedArray`` теряет маску), 1D и 4D+
    (ERROR на каждое сообщение). Всё это едет inline, как до 4.1. Импорт numpy — локальный
    (модуль не тянет numpy на уровне импорта; после первого вызова это поиск в sys.modules)."""
    from numpy import ndarray

    return (
        type(value) is ndarray
        and value.dtype.kind in "biufc"
        and value.dtype.isnative
        and value.ndim in (2, 3)
        and value.nbytes >= CLAIM_CHECK_MIN_NBYTES
    )


class _Ring:
    """Кольцо SHM-слотов ОДНОГО ключа data (Task 4.1, C7): своё имя слота, своя ёмкость,
    свой пул займов. Realloc одного кольца закрывает ТОЛЬКО свой слот — чужие кольца
    (и живые view читателей на них) не трогает.

    Состояние, которое до 4.1 жило плоскими полями middleware (``_allocated``,
    ``_alloc_shape``, ``_pool``, ...), переехало сюда; у ``FrameShmMiddleware`` на них
    остались read-only property-делегаты к кольцу ``frame`` (back-compat тестов/stats).
    Общие вещи (mm, owner, глубина, лог, reader) берутся у middleware ``mw``.
    """

    def __init__(self, mw: "FrameShmMiddleware", key: str, slot: str, pool: Optional[Any]) -> None:
        self.mw = mw
        self.key = key
        self.slot = slot
        self.allocated = False
        # H5b: создал ли слот САМ этот middleware (create_memory_dict) или ПРИНЯЛ чужой
        # (adopt PM-памяти). release_owned освобождает только СВОЁ.
        self.created_slot = False
        self.write_index = 0
        # Текущая ВЫДЕЛЕННАЯ ёмкость слота (h, w, c) + dtype. None — ещё не выделяли.
        self.alloc_shape: tuple[int, int, int] | None = None
        self.alloc_dtype: str | None = None
        self.pool: Optional[Any] = pool
        # H-ревью (E2): транзитный кэш handles на время ОДНОГО release() пачки этого кольца.
        self.release_handles_cache: Optional[Any] = None

    # --- ёмкость -------------------------------------------------------------------
    def fits(self, frame: Any) -> bool:
        """Влезает ли массив в текущую выделенную ёмкость (по каждому измерению + dtype)."""
        if self.alloc_shape is None:
            return False
        fh, fw, fc = FrameShmMiddleware._shape_hwc(frame)
        ah, aw, ac = self.alloc_shape
        return fh <= ah and fw <= aw and fc <= ac and str(frame.dtype) == self.alloc_dtype

    def ensure_capacity(self, frame: Any) -> None:
        """Lazy-аллокация при первом массиве + grow-only realloc при росте."""
        if not self.allocated or not self.fits(frame):
            self.allocate(frame)

    def allocate(self, frame: Any) -> None:
        """(Пере)выделить SHM-блоки под массив. Grow-only: ёмкость только растёт.

        Целевая форма = max(текущая_ёмкость, форма_массива) по каждому измерению —
        блок не сжимается (меньшие массивы читаются по header), но растёт под бо́льшие.
        При переаллокации закрывается ТОЛЬКО слот этого кольца (owner → unlink), новый
        новое ``name`` едет в ссылке каждого следующего сообщения → читатели следуют. Кольца других ключей
        не трогаются (C7): их слоты и живые view читателей остаются валидными.
        """
        mw = self.mw
        try:
            fh, fw, fc = FrameShmMiddleware._shape_hwc(frame)
            dtype = str(frame.dtype)
            # H5a: adopt-if-exists — PM в wire_setup мог УЖЕ создать (owner, slot).
            if not self.allocated:
                self.adopt_existing_slot_if_any()
            # Grow-only: не уменьшаем ёмкость (избегаем «качелей» при чередовании размеров).
            if self.alloc_shape is not None and dtype == self.alloc_dtype:
                ah, aw, ac = self.alloc_shape
                target = (max(ah, fh), max(aw, fw), max(ac, fc))
            else:
                target = (fh, fw, fc)

            # Уже выделено и форма не меняется — ничего не делаем (defensive).
            if self.allocated and target == self.alloc_shape and dtype == self.alloc_dtype:
                return

            # Переаллокация: закрыть СВОЙ старый блок (owner → unlink), затем создать новый.
            if self.allocated:
                try:
                    mw._mm.close_memory(mw._owner, self.slot)
                except Exception as e:
                    mw._log_error(f"FrameShmMiddleware: close old SHM before realloc: {e}")

            memory_names = {self.slot: (1, target, dtype)}
            mw._mm.create_memory_dict(mw._owner, memory_names, mw._coll)
            self.allocated = True
            self.created_slot = True  # H5b: слот создан ЭТИМ middleware → он его и освободит
            self.alloc_shape = target
            self.alloc_dtype = dtype
            self.write_index = 0  # свежие слоты — пишем с начала кольца
            # Ф7 G.5.d (В3): свежее кольцо (старые сегменты unlink'нуты) → free-list
            # сбрасывается в «всё свободно»; старые займы void. Только СВОЙ пул.
            if self.pool is not None:
                self.pool.reset()
        except Exception as e:
            mw._log_error(f"FrameShmMiddleware: allocate SHM error: {e}")

    def adopt_existing_slot_if_any(self) -> None:
        """H5a: если mm уже держит (owner, slot) — принять как выделенный, не создавать
        второй раз. Grow-only realloc в allocate пересоздаст лишь при росте массива."""
        mw = self.mw
        try:
            md = mw._mm.get_memory_data(mw._owner, self.slot)
        except Exception:
            return
        params = md.get("params", {}).get(self.slot) if md else None
        if not params:
            return
        _, existing_shape, existing_dtype = params
        self.allocated = True
        self.created_slot = False  # H5b: принят чужой слот (PM) — release его не трогает
        self.alloc_shape = tuple(existing_shape)  # type: ignore[assignment]
        self.alloc_dtype = str(existing_dtype)

    def release_owned(self) -> None:
        """H5b: освободить СВОЙ созданный слот на teardown (принятый PM-слот не трогает)."""
        mw = self.mw
        if mw._mm is None or not self.allocated or not self.created_slot:
            return
        try:
            mw._mm.close_memory(mw._owner, self.slot)
        except Exception as exc:  # noqa: BLE001 — teardown не критичен
            mw._log_error(f"FrameShmMiddleware: release_owned_memory failed: {exc}")
        self.allocated = False
        self.created_slot = False
        self.alloc_shape = None
        self.alloc_dtype = None

    # --- запись --------------------------------------------------------------------
    def acquire(self) -> Optional[int]:
        """Ф7 G.5.d (В3): индекс слота. loan — СВОБОДНЫЙ слот из free-list (None =
        исчерпание, сигнал поднимает middleware); off → слепой round-robin (бит-в-бит)."""
        if self.pool is not None:
            return self.pool.acquire()
        idx = self.write_index % self.mw._coll
        self.write_index += 1
        return idx

    def abort(self, idx: int) -> None:
        """Отменить loan без publish (WRITING→FREE). Без пула — no-op."""
        if self.pool is not None:
            self.pool.abort(idx)

    def write_and_publish(self, frame: Any, idx: int, dest: Dict[str, Any]) -> bool:
        """Записать массив в слот ``idx`` и (при loan) опубликовать; ссылка (пять полей
        формата 4.4: owner/slot/idx/gen/name) → ``dest``.

        True — записано (dest заполнен); False — write не удался (причина в
        ``mw._last_write_error``; вызывающий отменит loan через ``abort``)."""
        mw = self.mw
        try:
            written = mw._mm.write_frame(mw._owner, self.slot, frame, idx)
            if written:
                # 4.5c: байты считаем ТОЛЬКО после успешной записи (упавший write_frame не даёт байтов);
                # единая точка для generic-пути и wire-пути (on_send → _write_frame_into_slot).
                mw._add_bytes_written(int(getattr(frame, "nbytes", 0)))
                if self.pool is not None:
                    # loan/publish: слот занят num_consumers читателями; release (d-2) → 0.
                    self.pool.commit(idx, mw._num_consumers)
                shm_name, gen = written
                dest["owner"] = mw._owner
                dest["slot"] = self.slot
                dest["idx"] = idx
                dest["gen"] = gen
                dest["name"] = shm_name
                return True
            mw._last_write_error = "write_frame вернул None (нет слота/валидация)"
        except Exception as exc:  # noqa: BLE001 — причина едет в громкий лог (M2d)
            mw._last_write_error = repr(exc)
        return False

    # --- владение (release/reclaim) -------------------------------------------------
    def read_generation(self, idx: int) -> int:
        """Ф7 G.5.d-2: ТЕКУЩЕЕ поколение СВОЕГО слота (owner-side) — gen_reader пула.
        -1 при недоступности. Handles при release пачки сняты один раз (E2)."""
        mw = self.mw
        try:
            handles = self.release_handles_cache
            if handles is None:
                md = mw._mm.get_memory_data(mw._owner, self.slot) if mw._mm else None
                handles = md.get("handles") if md else None
            if handles and 0 <= idx < len(handles) and handles[idx] is not None:
                from ...shared_resources_module.memory.format import read_generation

                return read_generation(handles[idx].buf)
        except Exception:
            pass
        return -1

    def release(self, releases: list, evicted: bool) -> None:
        """Делегация пачки тикетов ЭТОГО кольца в его пул (см. release_slots)."""
        if self.pool is None or not releases:
            return
        if evicted:
            self.pool.release_evicted(releases)
            return
        mw = self.mw
        try:
            md = mw._mm.get_memory_data(mw._owner, self.slot) if mw._mm else None
            self.release_handles_cache = md.get("handles") if md else None
            self.pool.release(releases)
        finally:
            self.release_handles_cache = None

    def stat(self, name: str) -> int:
        """Счётчик пула кольца (0 без пула)."""
        return self.pool.snapshot_stats()[name] if self.pool is not None else 0


class FrameShmMiddleware:
    """Middleware для frame ↔ SHM на границах процессов.

    Args:
        memory_manager: MemoryManager из shared_resources_module (API write_images/
            read_images/create_memory_dict). Может быть ``None`` —
            запись деградирует в pickle-fallback (кадр остаётся в сообщении), но
            middleware всё равно должен быть зарегистрирован (Ф7 G.6 ревью, F3):
            иначе счётчик границ на этом пути не считает вовсе.
        owner: имя процесса-владельца SHM-региона (для write).
        slot: имя SHM-слота (для write).
        coll: количество SHM-слотов (размер ring buffer) — generic-путь.
        log_error: callback логирования ошибок — generic-путь.
        cache_shm_handles: кэшировать SHM-handles читателя (Ф7 G.3). None → env
            ``FW_SHM_HANDLE_CACHE`` → False (прежний open/close на кадр).

    Заголовок seqlock у слота ВСЕГДА (Task 4.4; флага ``FW_SHM_SEQLOCK`` больше нет): поколение
    записи слота — это и есть ``gen`` в ссылке, по нему reader отличает свою запись от переписанной.

    Attributes:
        frame_boundary_crossings: Ф7 G.6 — сколько раз кадр реально пересёк границу
            процесса через ЭТОТ middleware (send-сторона, SHM-успех ИЛИ
            pickle-fallback — оба пути кладут кадр на исходящий транспорт; F1 —
            считается на КАЖДЫЙ send, включая повторные при fan-out на несколько
            targets, не только на первый «настоящий» стрип). Plain int, БЕЗ lock
            (ревью 2026-07-13, F5): диагностическая метрика на hot path, не
            требующая линеаризуемости — under GIL инкремент `+= 1` практически
            атомарен для одного потока-писателя (send всегда идёт из одного
            воркера на middleware); при регистрации через
            ``RouterManager.register_frame_middleware`` агрегируется в
            ``introspect.router_stats`` на чтении (без lock на самом send-пути).
        frame_pickle_fallbacks: Ф7 G.3(d) — сколько кадров ушло pickle-fallback'ом
            при СБОЕ SHM-write (mm есть, но write не удался — реальная деградация
            ×3 латентность). Plain int по образцу frame_boundary_crossings;
            агрегируется в get_stats. Случай mm=None (SHM не сконфигурирован в
            процессе) НЕ считается — это pickle-by-design, не деградация.
    """

    def __init__(
        self,
        memory_manager: Any,
        owner: str,
        slot: str = "output_frames",
        coll: Optional[int] = None,
        log_error: Callable[[str], None] | None = None,
        cache_shm_handles: Optional[bool] = None,
        owner_incarnation: Optional[bool] = None,
        handle_cache_cap: int = _HANDLE_CACHE_CAP,
        zero_copy: Optional[bool] = None,
        loan_protocol: Optional[bool] = None,
        num_consumers: int = 1,
        pool: Optional[Any] = None,
        reader: Optional[Any] = None,
    ) -> None:
        self._mm = memory_manager
        self._owner = owner
        self._slot = slot
        # Ф7 G.4.b: глубина кольца per-camera (число SHM-слотов round-robin). Явный
        # coll (не None, >0) выигрывает — приходит из рецепта/wire (buffer_slots) на
        # конкретную камеру; иначе при FW_QOS_PROFILES — боевая глубина из QoS-профиля
        # data (history_depth=4, «несколько кадров на джиттер»); иначе прежний дефолт 3
        # (откат бит-в-бит). Каждый источник = свой owner = своё независимое кольцо
        # (изоляция per-camera по построению; общего слота нет).
        self._coll = self._resolve_ring_depth(coll)
        self._log_error = log_error or (lambda msg: None)
        # Ф7 G.6 (F5 ревью 2026-07-13): собственный счётчик, БЕЗ колбэка в
        # RouterManager (тот давал reference-cycle middleware↔router + третий lock
        # на send-пути). RouterManager сам суммирует этот атрибут у всех
        # зарегистрированных middleware в get_stats() — см. класс-докстринг.
        self.frame_boundary_crossings = 0
        # Ф7 G.3(d): громкий pickle-fallback (счётчик всегда, WARNING throttled).
        self.frame_pickle_fallbacks = 0
        # 4.5c: объём, реально записанный в SHM / прочитанный из SHM (байты массивов). Замок, а не
        # голый ``+=``: писать могут поток-продюсер и потоки executor'а, а ``+=`` по атрибуту не атомарен
        # при переключении GIL (потерянное приращение) — приёмка требует точную сумму.
        self._bytes_lock = threading.Lock()
        self._bytes_written = 0
        self._bytes_read = 0
        # M2c / Task 4.4: torn-чтения (перезапись слота во время чтения по ссылке) считает
        # reader — ``frame_torn_reads`` ниже проецирует его счётчик (агрегируется в get_stats).
        # 4.1-fix: тикетов release с неизвестным ``slot`` отброшено (не наше кольцо —
        # не трогаем ничей займ). ponytail: не в get_shm_stats (набор ключей закреплён
        # и уходит в телеметрию) — добавить туда отдельной задачей, если понадобится.
        self.frame_release_unknown_slot = 0
        # Ф7 G.5.c: post-use re-check zero-copy view — слот перезаписан под живым view.
        # H-задача (Этап 2): счётчик теперь у reader'а (`self._reader.stale_drops`),
        # frame_stale_drops — read-only property (агрегируется в get_stats → heartbeat).
        # M2d: причина последнего сбоя записи — для громкого fallback-лога.
        self._last_write_error = ""
        # M2a: троттлинг «frame не восстановлен» (штатный drop после G.7, не ERROR-спам).
        self._restore_fail_count = 0
        # 4.4c: сегмент ссылки уже отвязан (realloc кольца/смена инкарнации владельцем) — это stale
        # (ячейка переписана/исчезла ДО чтения), но reader этого не видит (open бросает раньше
        # проверки поколения) — считаем здесь и складываем в ``frame_stale_drops``.
        self._stale_unlinked_drops = 0
        # 4.4d: доначисление executor'а — батч из N выходов дропнут целиком, reader посчитал 1
        # (``all()`` встал на первой ссылке), остальные N-1 сообщений — сюда (``note_stale_drops``).
        # Без замка, как ``_stale_unlinked_drops``: потоки (executor / приём) пишут разные счётчики
        # и читаются только на heartbeat-снимке.
        self._stale_batch_drops = 0
        # Task 4.1: состояние слота (allocated/created/ёмкость/seqlock/пул) живёт в
        # кольцах per-key (``_Ring``), см. ``_rings`` ниже; плоские ``_allocated``,
        # ``_alloc_shape``, ``_pool``... — read-only делегаты к кольцу ``frame``.
        # H4: кэш handles БЕЗОПАСЕН только когда имя меняется на КАЖДЫЙ realloc
        # (owner_incarnation). Иначе realloc = unlink+create ТОГО ЖЕ имени (POSIX,
        # incarnation off) → cache hit на осиротевшие страницы → замороженный кадр №1
        # навсегда, тихо. Жёсткая связка: кэш активен ТОЛЬКО при owner_incarnation.
        self._owner_incarnation = self._resolve_bool_flag(owner_incarnation, "FW_SHM_OWNER_INCARNATION")
        cache_requested = self._resolve_bool_flag(cache_shm_handles, "FW_SHM_HANDLE_CACHE")
        if cache_requested and not self._owner_incarnation:
            self._log_error(
                "FrameShmMiddleware: cache_shm_handles запрошен БЕЗ owner_incarnation — "
                "кэш ОТКЛЮЧЁН (H4: риск замороженного кадра при realloc с переиспользованием имени)"
            )
            self._cache_shm_handles = False
        else:
            self._cache_shm_handles = cache_requested
        self._handle_cache_cap = max(1, int(handle_cache_cap))  # L4: конфигурируемый кэп
        # Ф7 G.5.b: zero-copy чтение (restore_frame отдаёт VIEW в слот, без .copy()).
        # ЖЁСТКАЯ связка с handle-кэшем: без него сегмент закрывается сразу после
        # чтения (`shm.close()` в finally) → view повис бы (use-after-free/BufferError).
        # Поэтому zero-copy активен ТОЛЬКО при живом кэше (который сам требует
        # owner_incarnation, H4). Безопасность удержания view после возврата (слот не
        # перезаписан) — seqlock read-moment (здесь) + post-use re-check (G.5.c).
        zero_copy_requested = self._resolve_bool_flag(zero_copy, "FW_SHM_ZERO_COPY")
        if zero_copy_requested and not self._cache_shm_handles:
            self._log_error(
                "FrameShmMiddleware: zero_copy запрошен БЕЗ активного handle-кэша — "
                "ОТКЛЮЧЁН (view повис бы на закрытом сегменте; кэш требует "
                "FW_SHM_HANDLE_CACHE + FW_SHM_OWNER_INCARNATION)"
            )
            self._zero_copy = False
        else:
            self._zero_copy = zero_copy_requested
        # Ф7 H-задача (Этап 2): reader-side тракт (кэш handles + zero-copy view + post-use
        # re-check) вынесен за фасад ``FrameReader`` в модуль памяти. Транспорт держит
        # reader через DI и делегирует; синхронизация кэша — внутреннее дело reader'а
        # (гонка close↔read_generation закрыта: executor больше не лезет в приватный кэш).
        # Флаги уже согласованы выше (zero_copy ⊃ cache ⊃ owner_incarnation).
        # DI (H-ревью 2026-07-14): инжектированный ``reader`` выигрывает — подмена
        # реализации (напр. Rust/iceoryx2 под тем же ``FrameReader``) не трогает транспорт;
        # None → дефолт-фабрика ``ShmFrameReader`` (обычный путь).
        if reader is not None:
            self._reader: Any = reader
        else:
            from ...shared_resources_module.memory.reader import ShmFrameReader

            self._reader = ShmFrameReader(
                cache_enabled=self._cache_shm_handles,
                zero_copy=self._zero_copy,
                cap=self._handle_cache_cap,
                log=self._log_error,
            )
        # Ф7 H-задача (консолидация памяти): семантика владения слотом кольца
        # (free-list/refcount/release/reclaim) вынесена за фасад ``FramePool`` в модуль
        # памяти (`shared_resources_module.memory.pool`). Транспорт держит пул через DI и
        # делегирует — раньше ~200 строк владения жили ЗДЕСЬ, в транспортном модуле.
        # refcount мутирует ТОЛЬКО этот (owner) процесс (кросс-процессного atomic RMW нет,
        # §8 плана). loan-on-write берёт СВОБОДНЫЙ слот (acquire) вместо слепого
        # round-robin, ставит refcount=num_consumers (commit); release (d-2) декрементит.
        # Пул создаётся ТОЛЬКО под флагом; off → пул=None, слепой round-robin
        # (``self._write_index``), бит-в-бит прежнее поведение.
        # Ф7 G.7. Две РАЗНЫЕ роли loan-протокола, не путать:
        #  1) КОНСЬЮМЕР — дочитав входной zero-copy view, шлёт release ВВЕРХ владельцу
        #     (``pipeline_executor._loan_active``). Зависит ТОЛЬКО от флага (не от своего
        #     fan-out): процесс points читает кадры lines и ОБЯЗАН их релизить, даже если
        #     сам фанится лишь в GUI. Поэтому ``loan_protocol_enabled`` = сырой флаг.
        #  2) ВЛАДЕЛЕЦ — держит пул слотов на СВОЁМ выходе, commit refcount=num_consumers.
        #     Осмыслен ТОЛЬКО при ≥1 loan-aware потребителе (том, кто пришлёт release).
        #     copy-out терминалы (GUI: кадр КОПИРУЮТ, release НЕ шлют) в счёт НЕ входят.
        #     Владелец с fan-out'ом ТОЛЬКО в GUI (напр. points→[gui]): 0 loan-aware →
        #     refcount застрял бы (некому декрементить) → free-list исчерпание → вечный
        #     drop-на-источнике (воспроизведено live). Поэтому пул создаётся лишь при
        #     num_consumers>0 (ниже); иначе — слепой round-robin (В1: seqlock + глубокое
        #     кольцо защищают copy-out чтение). Счёт из топологии проводит caller.
        self._loan_protocol = self._resolve_bool_flag(loan_protocol, "FW_SHM_LOAN_PROTOCOL")
        self._num_consumers = max(0, int(num_consumers))
        # Per-write сигнал «drop-на-источнике по исчерпанию» (отличить от write-fail →
        # pickle-fallback): send-middleware по нему возвращает None (дроп send).
        self._last_loan_exhausted = False
        # Task 4.1 (C7): одно кольцо на ключ data. Ключ ``frame`` — слот ``slot`` как
        # прежде (back-compat читателей, stats, adopt PM wire_setup); остальные ключи —
        # слот ``<slot>__<key>``, кольцо создаётся лениво на первом крупном массиве.
        # Copy-on-write: писатель подменяет dict целиком, читатели (release на
        # message_processor, get_stats) берут снимок ссылки — без гонки «dict changed size».
        # Пул кольца ``frame`` (тип: FramePool). DI (H-ревью 2026-07-14): инжектированный
        # ``pool`` выигрывает (подмена на Rust/iceoryx2 не трогает транспорт); None + флаг →
        # дефолт-фабрика ``LoanLedger``; None + флаг off → пул=None (слепой round-robin).
        # Ф7 G.7: пул только при num_consumers>0 (copy-out/GUI исключены из счёта).
        self._pooled = pool is not None or (self._loan_protocol and self._num_consumers > 0)
        frame_ring = _Ring(self, FRAME_KEY, self._slot, pool)
        if frame_ring.pool is None and self._pooled:
            frame_ring.pool = self._make_pool(frame_ring)
        self._frame_ring = frame_ring
        self._rings: Dict[str, _Ring] = {FRAME_KEY: frame_ring}

    def _make_pool(self, ring: _Ring) -> Any:
        """Дефолтный пул займов кольца. Import runtime-local — coupling
        router→shared_resources остаётся runtime. gen_reader = поколение СВОЕГО слота
        кольца → пул SHM-агностичен."""
        from ...shared_resources_module.memory.pool import LoanLedger

        return LoanLedger(self._coll, gen_reader=ring.read_generation)

    def _ring_for(self, key: str) -> _Ring:
        """Кольцо ключа; не-``frame`` ключ получает своё кольцо лениво (слот ``<slot>__<key>``).
        Создаёт только поток-писатель (send-путь, single-writer)."""
        ring = self._rings.get(key)
        if ring is None:
            ring = _Ring(self, key, f"{self._slot}__{key}", None)
            if self._pooled:
                ring.pool = self._make_pool(ring)
            self._rings = {**self._rings, key: ring}  # copy-on-write (см. __init__)
        return ring

    def _ring_by_slot(self, slot: Any) -> Optional[_Ring]:
        """Кольцо по имени слота из тикета. Нет ``slot`` → кольцо ``frame`` (до 4.1 все
        тикеты шли в единственный пул — back-compat тикетов без ``slot``).

        4.1-fix (ревью 4.1, находка 3): НЕИЗВЕСТНЫЙ непустой ``slot`` → ``None``, тикет
        отбрасывается. Раньше он падал в кольцо ``frame``, и ``evicted=True`` (без
        generation-guard) снимал чужой займ кадра."""
        if not slot:
            return self._frame_ring
        for ring in self._rings.values():
            if ring.slot == slot:
                return ring
        return None

    def _sum_stat(self, name: str) -> int:
        return sum(ring.stat(name) for ring in list(self._rings.values()))

    # --- back-compat: плоское состояние слота = кольцо ``frame`` (read-only) ---------
    @property
    def _pool(self) -> Optional[Any]:
        return self._frame_ring.pool

    @property
    def _allocated(self) -> bool:
        return self._frame_ring.allocated

    @property
    def _created_slot(self) -> bool:
        return self._frame_ring.created_slot

    @property
    def _alloc_shape(self) -> tuple[int, int, int] | None:
        return self._frame_ring.alloc_shape

    @property
    def _alloc_dtype(self) -> str | None:
        return self._frame_ring.alloc_dtype

    @property
    def _write_index(self) -> int:
        return self._frame_ring.write_index

    def _frame_fits(self, frame: Any) -> bool:
        return self._frame_ring.fits(frame)

    def _allocate_shm(self, frame: Any) -> None:
        self._frame_ring.allocate(frame)

    def _adopt_existing_slot_if_any(self) -> None:
        self._frame_ring.adopt_existing_slot_if_any()

    def _read_own_slot_generation(self, idx: int) -> int:
        return self._frame_ring.read_generation(idx)

    @property
    def loan_protocol_enabled(self) -> bool:
        """Ф7 G.5 ревью-фикс 13: активен ли loan-протокол (сырой флаг). Роль КОНСЬЮМЕРА —
        executor по нему решает слать ли release ВВЕРХ владельцу входного view. НЕ означает
        «этот процесс держит СВОЙ пул»: пул есть только при ``num_consumers>0`` (проверять
        ``_pool is not None``). Разнос ролей — Ф7 G.7 (иначе GUI-only процесс переставал
        релизить кадры upstream'а)."""
        return self._loan_protocol

    @property
    def ring_depth(self) -> int:
        """Ф7 G.5 ревью-фикс 6: глубина кольца owner'а (для расчёта порога флаша release
        у consumer'а — порог не должен превышать реальную глубину, иначе тикеты не
        набираются и free-list голодает)."""
        return self._coll

    # Ф7 H-задача: счётчики loan-цикла — read-only проекция статов пула (единственный
    # источник). RouterManager.get_stats суммирует их через getattr у всех middleware
    # (property прозрачна для getattr). Пул=None (флаг off) → 0 (бит-в-бит: раньше тоже 0).
    @property
    def frame_loan_exhausted(self) -> int:
        """Исчерпаний free-list (громкий drop-на-источнике: читатели отстали)."""
        return self._sum_stat("loan_exhausted")

    @property
    def frame_slots_released(self) -> int:
        """Слотов освобождено release'ами (здоровье loan-цикла)."""
        return self._sum_stat("slots_released")

    @property
    def frame_slots_reclaimed(self) -> int:
        """Займов реклеймлено после смерти читателя (kill-9 без release)."""
        return self._sum_stat("slots_reclaimed")

    @property
    def frame_loans_released_on_evict(self) -> int:
        """LIVE-2: займов освобождено при вытеснении сообщения из полной очереди до
        прочтения (release-on-evict). Без этого пути займ вытесненного кадра не отпустил
        бы никто → free-list деградировал до перманентной смерти кольца. Пул=None → 0."""
        return self._sum_stat("slots_released_on_evict")

    @property
    def frame_stale_drops(self) -> int:
        """СООБЩЕНИЙ отброшено по расхождению поколения (Task 4.4: ячейка переписана ДО чтения;
        Ф7 G.5.c: view пережил перезапись) — счётчик reader'а + отвязанные сегменты ссылок (4.4c) +
        доначисление ``note_stale_drops``. Единица — ОДНО отброшенное сообщение на обоих путях
        (4.4d): приём останавливается на первой провалившейся ссылке, дверь отправки считает item
        один раз, дроп батча из N выходов executor'ом = 1 (reader) + N-1 (``note_stale_drops``)."""
        return self._reader.stale_drops + self._stale_unlinked_drops + self._stale_batch_drops

    def note_stale_drops(self, n: int) -> None:
        """Публичный контракт для ``PipelineExecutor`` (4.4d): доначислить ``n`` отброшенных сообщений
        в ``frame_stale_drops``. Executor зовёт с ``N - 1`` при дропе батча из N выходов — первое
        сообщение уже посчитал reader. ``n <= 0`` — no-op."""
        if n > 0:
            self._stale_batch_drops += n

    def _add_bytes_written(self, n: int) -> None:
        """4.5c: прибавить ``n`` байт к счётчику записи (под замком — см. комментарий в ``__init__``)."""
        with self._bytes_lock:
            self._bytes_written += n

    def _add_bytes_read(self, n: int) -> None:
        """4.5c: прибавить ``n`` байт к счётчику чтения (под замком)."""
        with self._bytes_lock:
            self._bytes_read += n

    @property
    def bytes_written(self) -> int:
        """4.5c: суммарно байт массивов, успешно записанных в слоты СВОИХ колец (любой ключ)."""
        return self._bytes_written

    @property
    def bytes_read(self) -> int:
        """4.5c: суммарно байт массивов, успешно прочитанных по ссылке (stale/torn/битая — 0)."""
        return self._bytes_read

    def ring_info(self) -> list[dict]:
        """4.5c: описание созданных колец — по записи ``{key, name, depth}`` на кольцо
        (``name`` — имя слота кольца, ``depth`` — число ячеек round-robin)."""
        return [{"key": r.key, "name": r.slot, "depth": self._coll} for r in list(self._rings.values())]

    @property
    def frame_restore_failures(self) -> int:
        """Ссылок не восстановлено из-за сбоя открытия/битой ссылки (кроме штатного stale по
        поколению и отвязанного сегмента — те в ``frame_stale_drops``). Read-only проекция счётчика,
        из-за которого throttled-лог «не восстановлен» видит только каждое 300-е."""
        return self._restore_fail_count

    @property
    def frame_torn_reads(self) -> int:
        """Task 4.4: СООБЩЕНИЙ отброшено из-за перезаписи слота ВО ВРЕМЯ чтения по ссылке (единица —
        сообщение, не ссылка, 4.4c: чтение останавливается на первой провалившейся) — проекция
        счётчика reader'а (подменный reader без ``torn_reads`` → 0)."""
        return getattr(self._reader, "torn_reads", 0)

    @property
    def frame_handle_cache_size(self) -> int:
        """Ф7 G.7 (0.5): размер reader-кэша SHM-handle — read-only проекция reader'а.

        Под zero-copy эвикция отключена → на soak следим за ростом на инкарнацию
        (резидуал G.5). Без handle-кэша (флаг off) — 0."""
        return self._reader.cache_size

    @staticmethod
    def _resolve_bool_flag(explicit: Optional[bool], env_name: str) -> bool:
        """Разрешить булев флаг: ctor (не None) > env ``env_name`` (в т.ч. ``=0``) > default.

        Default теперь берётся из реестра feature_flags."""
        from ...config_module.feature_flags import resolve

        return resolve(env_name, explicit)

    @classmethod
    def _resolve_ring_depth(cls, explicit: Optional[int]) -> int:
        """Глубина кольца SHM-слотов (Ф7 G.4.b, B-8).

        Приоритет: явный ``coll`` (не None, >0 — из рецепта/wire per-camera) > при
        ``FW_QOS_PROFILES`` боевая глубина из QoS-профиля data (``history_depth``,
        «несколько кадров на джиттер») > прежний дефолт 3 (откат бит-в-бит). Раньше
        глубина была ЖЁСТКО 3 везде, а ``buffer_slots`` из wire-команды игнорировался
        («информативно») — кольцо не настраивалось per-camera (B-8).
        """
        if explicit is not None and explicit > 0:
            return int(explicit)
        if cls._resolve_bool_flag(None, "FW_QOS_PROFILES"):
            from ...shared_resources_module.qos import qos_for

            return max(1, qos_for("data").history_depth)
        return 3

    def _bump_frame_hops(self, container: dict) -> None:
        """Инкремент per-item поля frame_hops + агрегатного счётчика (Ф7 G.6).

        Общий хелпер для strip_and_write/on_send (F6a ревью 2026-07-13 — не
        дублировать инкремент в двух местах). ``container`` — тот dict, что
        реально уезжает по IPC (item для generic-пути, data для on_send-пути).
        """
        container["frame_hops"] = int(container.get("frame_hops") or 0) + 1
        self.frame_boundary_crossings += 1

    def _bump_boundary_only(self) -> None:
        """Учесть границу БЕЗ инкремента per-item поля (F1 — повторный send того
        же item на fan-out: поле уже несёт значение первого стрипа, задваивать
        его для второго/третьего target не нужно — item ОДИН и тот же объект,
        см. strip_data_frame_on_send; агрегатный счётчик, наоборот, обязан расти
        на каждый РЕАЛЬНЫЙ IPC-send, иначе недосчитывает границы при fan-out)."""
        self.frame_boundary_crossings += 1

    def _note_pickle_fallback(self, where: str) -> None:
        """Ф7 G.3(d): учесть громкий pickle-fallback (сбой SHM-write, не mm=None).

        Счётчик растёт всегда (наблюдаемость → get_stats → state); WARNING —
        throttled (первый + каждый N-й), чтобы не спамить hot-path лог. Латентность
        ×3 больше не невидима.
        """
        self.frame_pickle_fallbacks += 1
        if self.frame_pickle_fallbacks == 1 or self.frame_pickle_fallbacks % _PICKLE_WARN_EVERY == 0:
            self._log_error(
                f"FrameShmMiddleware: кадр ушёл pickle-fallback (медленно, ×3 латентность) "
                f"[{where}; owner={self._owner}/{self._slot}; причина={self._last_write_error}; "
                f"всего={self.frame_pickle_fallbacks}]"
            )

    # ------------------------------------------------------------------
    # Reader-side тракт (Ф7 H-задача, Этап 2): делегация в FrameReader
    # ------------------------------------------------------------------

    def close_handle_cache(self) -> None:
        """Закрыть все кэшированные SHM-handles (teardown wire/процесса) — делегация."""
        self._reader.close()

    def release_owned_memory(self) -> None:
        """H5b: освободить SHM-блоки, СОЗДАННЫЕ этим middleware (owner-side), на teardown.

        wire.deconfigure раньше освобождал только reader-кэш, но НЕ память владельца →
        каждый цикл configure/deconfigure копил сегменты (POSIX). Здесь owner закрывает+
        unlink'ает СВОЙ слот; сброс _allocated → следующий configure выделит заново.
        ПРИНЯТУЮ (adopt) PM-память НЕ трогает (``_created_slot`` False).
        Task 4.1: по ВСЕМ кольцам (frame + кольца крупных ключей).
        """
        for ring in list(self._rings.values()):
            ring.release_owned()

    def frame_view_valid(self, ref: Dict[str, Any]) -> bool:
        """Ф7 G.5.c — post-use re-check: жив ли ещё zero-copy view (слот не перезаписан).

        Task 4.4: сверяет ТЕКУЩЕЕ поколение слота ``ref["name"]`` с ``ref["gen"]`` — тем, что
        писатель поставил в ссылку (а не с поколением, увиденным при чтении). Делегирует в
        ``FrameReader.view_valid``: совпало → валиден; разошлось / handle эвиктнут / gen<0 →
        drop (счётчик ``frame_stale_drops`` у reader'а), НЕ порча. Публичный контракт для
        ``PipelineExecutor`` и двери отправки. Синхронизация — внутри reader'а (свой lock)."""
        return self._reader.view_valid(ref["name"], ref["gen"])

    # ------------------------------------------------------------------
    # Единое ядро записи кадра в SHM (Ф7 G.3a — канон generic)
    # ------------------------------------------------------------------

    def _write_frame_into_slot(self, frame: Any, dest: Dict[str, Any]) -> bool:
        """Записать кадр в SHM-слот и вписать координаты В ``dest`` (тот же dict, что
        уезжает по IPC). M3: НЕ создаём новый dict на кадр (per-frame путь без лишних
        аллокаций — правило G.9).

        Единое ядро для strip_and_write И on_send (Ф7 G.3a): lazy-alloc + realloc при
        росте кадра + round-robin по слотам. Заголовок seqlock у слота
        всегда; в ``dest`` кладётся ссылка ``{owner, slot, idx, gen, name}`` (поколение записи — в
        ``gen``, отдельных флагов формата нет).

        Returns:
            True — записано в SHM, координаты в ``dest``; False — mm отсутствует или
            write не удался (причина в ``self._last_write_error`` для громкого лога).
        """
        self._last_loan_exhausted = False
        if self._mm is None:
            self._last_write_error = "memory_manager=None"
            return False
        ring = self._frame_ring
        # Lazy allocation при первом кадре + ПЕРЕАЛЛОКАЦИЯ при росте кадра (resize).
        ring.ensure_capacity(frame)
        idx = self._acquire_slot(ring)
        if idx is None:
            return False  # loan-исчерпание (drop-на-источнике; счётчик — в _acquire_slot)
        if ring.write_and_publish(frame, idx, dest):
            return True
        # Ф7 H-ревью: write не удался → ОТМЕНИТЬ loan (WRITING→FREE), иначе зарезервированный
        # acquire'ом слот утёк бы навсегда (ёмкость кольца тает). loan↔publish/abort (iceoryx2).
        ring.abort(idx)
        return False

    def _acquire_slot(self, ring: Optional[_Ring] = None) -> Optional[int]:
        """Ф7 G.5.d (В3): выбор индекса слота кольца (по умолчанию ``frame``). loan-протокол
        — СВОБОДНЫЙ слот из free-list (``acquire`` резервирует WRITING); нет свободных →
        None + громкий drop-на-источнике (не write-fail). off → слепой round-robin."""
        ring = ring or self._frame_ring
        idx = ring.acquire()
        if idx is None:
            self._note_loan_exhausted(ring)
        return idx

    def _write_item_arrays(self, item: Dict[str, Any], entries: list) -> None:
        """Task 4.1: записать массивы item'а (``frame`` + крупные ключи) в их кольца.

        Две фазы — займы ВСЕГО сообщения берутся до первой записи:
          1. ёмкость + ``acquire`` по каждому кольцу. Исчерпание на ЛЮБОМ кольце →
             займы, уже взятые под это сообщение другими кольцами, отменяются (``abort``),
             ``_last_loan_exhausted`` → send-middleware дропает всё сообщение (C5, как
             drop кадра до 4.1). Без отмены слот кольца ``frame`` утёк бы в WRITING навсегда.
          2. запись + publish. Сбой записи ОДНОГО ключа → abort его займа, массив остаётся
             inline (громкий pickle-fallback); остальные ключи идут ссылкой.

        Task 4.4: ссылка на КАЖДЫЙ ключ (и ``frame``) — ``item["_shm_refs"][key]``; исходящий
        ``_shm_refs`` — НОВЫЙ dict только со СВОИМИ ссылками (унаследованные от предыдущего хопа
        не пересылаются никогда: один хоп), массив из item убирается.
        """
        planned: list = []
        for key, arr in entries:
            ring = self._ring_for(key)
            ring.ensure_capacity(arr)
            idx = self._acquire_slot(ring)
            if idx is None:
                for _key, _arr, taken_ring, taken_idx in planned:
                    taken_ring.abort(taken_idx)
                return
            planned.append((key, arr, ring, idx))

        own_refs: Dict[str, Any] = {}
        for key, arr, ring, idx in planned:
            ref: Dict[str, Any] = {}
            if ring.write_and_publish(arr, idx, ref):
                own_refs[key] = ref
                item.pop(key, None)
                continue
            ring.abort(idx)
            self._note_pickle_fallback(f"strip_and_write[{key}]")
        if own_refs:
            item[SHM_REFS_KEY] = own_refs
        else:
            item.pop(SHM_REFS_KEY, None)

    def _has_own_ref(self, container: Any) -> bool:
        """Task 4.4: несёт ли dict ссылку СВОЕГО владельца — признак fan-out повтора (item уже
        стрипнут для другого target). Унаследованные ссылки (owner другой) — не признак."""
        refs = container.get(SHM_REFS_KEY) if isinstance(container, dict) else None
        if not isinstance(refs, dict):
            return False
        return any(isinstance(r, dict) and r.get("owner") == self._owner for r in refs.values())

    def _inputs_still_valid(self, item: Dict[str, Any]) -> bool:
        """Дверь отправки (Task 4.4): все ли входные view item'а пережили копию в свои кольца.

        Проверка идёт ПОСЛЕ записи (seqlock-идиома: скопировали, потом убедились, что источник не
        менялся). Останавливается на ПЕРВОЙ перезаписанной ссылке — ``frame_stale_drops`` растёт
        ОДИН раз на item, а не на ссылку."""
        for ref in item.get(SHM_VIEWS_KEY) or ():
            if not self.frame_view_valid(ref):
                return False
        return True

    def _count_unknown_slot_ticket(self, slot: Any) -> None:
        """4.1-fix: учесть отброшенный тикет с неизвестным ``slot`` (счётчик всегда,
        лог — первый и каждый N-й, как pickle-fallback)."""
        self.frame_release_unknown_slot += 1
        n = self.frame_release_unknown_slot
        if n == 1 or n % _PICKLE_WARN_EVERY == 0:
            self._log_error(
                f"FrameShmMiddleware: тикет release с неизвестным slot={slot!r} отброшен "
                f"[owner={self._owner}; кольца={sorted(r.slot for r in self._rings.values())}; "
                f"всего={n}]"
            )

    def _note_loan_exhausted(self, ring: Optional[_Ring] = None) -> None:
        """Ф7 G.5.d (В3): free-list исчерпан → back-pressure = ГРОМКИЙ drop-на-источнике
        (кадр не уходит; счётчик всегда, WARNING throttled). Живую камеру НЕ блокируем.

        Ф7 H-задача: счётчик инкрементит пул внутри ``acquire()`` (при None); здесь —
        только per-write сигнал + throttled лог (сумма по кольцам)."""
        self._last_loan_exhausted = True
        slot = ring.slot if ring is not None else self._slot
        n = self.frame_loan_exhausted
        if n == 1 or n % _PICKLE_WARN_EVERY == 0:
            self._log_error(
                f"FrameShmMiddleware: free-list исчерпан (читатели отстали), кадр дропнут "
                f"на источнике [owner={self._owner}/{slot}; глубина={self._coll}; "
                f"всего={n}]"
            )

    def release_slots(self, releases: list, evicted: bool = False) -> None:
        """Ф7 G.5.d-2 (В3): owner-side release-handler — тонкий адаптер к пулам (H-задача).

        Consumer, дочитав view, шлёт пачку тикетов ``{slot?, index, generation, reader}``;
        Task 4.1: тикеты раскладываются по кольцам по ``slot`` (нет → кольцо
        ``frame``, back-compat), каждое кольцо делегирует декремент в СВОЙ
        ``FramePool.release`` (guard'ы — refcount==0/stale generation/dup reader — внутри
        пула; generation читает ``gen_reader`` кольца). refcount мутирует ТОЛЬКО этот
        (owner) процесс. Любая ошибка учёта безопасна: В1 re-check ловит преждевременное
        освобождение (writer перезапишет → drift → drop, не corruption).

        ``evicted=True`` (LIVE-2): пачка пришла не от дочитавшего потребителя, а от
        транспорта, ВЫТЕСНИВШЕГО сообщение из полной очереди до прочтения. Тикеты поколения
        не несут → ``FramePool.release_evicted`` (без generation-guard). Без этого займ
        вытесненного сообщения утекал бы навсегда (перманентная смерть кольца).
        """
        if not releases:
            return
        by_ring: Dict[int, tuple] = {}
        for ticket in releases:
            slot = ticket.get("slot") if isinstance(ticket, dict) else None
            ring = self._ring_by_slot(slot)
            if ring is None:
                self._count_unknown_slot_ticket(slot)
                continue
            by_ring.setdefault(id(ring), (ring, []))[1].append(ticket)
        for ring, tickets in by_ring.values():
            ring.release(tickets, evicted)

    def reclaim_reader(self, dead_reader: str) -> int:
        """Ф7 G.5.e (В3): реклейм займов МЁРТВОГО читателя (kill-9 без release) — адаптер.

        При fan-out мёртвый reader держал все слоты, которые ещё НЕ отпустил → пул
        декрементит за него (тот же учёт, инициатор — владелец по confirmed-death
        соседа: supervisor/incarnation). Идемпотентно (повторный вызов после реклейма →
        0). Task 4.1: по ВСЕМ кольцам. Транспорт лишь ГРОМКО логирует результат
        (у пула логгера нет). Вторая линия — startup-cleanup осиротевших сегментов G.3(c);
        В1 re-check ловит любую ошибку учёта. Возвращает число реклеймленных займов."""
        if not dead_reader:
            return 0
        reclaimed = 0
        for ring in list(self._rings.values()):
            if ring.pool is not None:
                reclaimed += ring.pool.reclaim(dead_reader)
        if reclaimed:
            self._log_error(
                f"FrameShmMiddleware: реклейм {reclaimed} займов мёртвого читателя "
                f"'{dead_reader}' [owner={self._owner}/{self._slot}*]"
            )
        return reclaimed

    # ------------------------------------------------------------------
    # Generic data-pipeline API (канон): strip_and_write / restore_frame
    # ------------------------------------------------------------------

    def restore_frame(self, msg: dict) -> dict:
        """Восстановить массивы из ссылок ``data["_shm_refs"]`` (Task 4.4: включая ``frame``).

        ``frame`` -> ``msg["frame"]``; остальные ключи -> ``data[key]`` (Task 4.1). Чтение — по
        ``ref["name"]`` со сверкой поколения ``ref["gen"]`` (view при zero_copy, иначе копия;
        перезаписанная ячейка / рваное чтение -> ``None`` + счётчик, НЕ чужие пиксели).
        Ссылки, восстановленные view, записываются в ПРОЦЕСС-ЛОКАЛЬНЫЙ ключ ``data["_shm_views"]``
        — по ним executor и дверь отправки проверяют, что view пережил обработку.

        Атомарность (4.4c): ссылки одного сообщения читаются по порядку и чтение ОСТАНАВЛИВАЕТСЯ на
        первой, что вернула ``None``; всё уже восстановленное снимается, в ``data`` ставится метка
        ``_shm_dropped`` — сообщение отброшено целиком (никогда ``frame`` без ``mask``).

        Pickle-fallback: ``frame`` уже в сообщении (не через SHM) — берётся как есть.
        """
        data = msg.get("data", msg)
        if not isinstance(data, dict):
            return msg
        if msg.get(FRAME_KEY) is None and data.get(FRAME_KEY) is not None:
            msg[FRAME_KEY] = data[FRAME_KEY]
        refs = data.get(SHM_REFS_KEY)
        if refs:
            views = self._restore_refs(msg, data, refs, allow_view=True)
            if views is None:
                # 4.4c: item атомарен — одна нечитаемая ссылка отбрасывает ВСЁ сообщение; приёмник
                # (DataReceiver) по метке не строит item.
                data[SHM_DROPPED_KEY] = True
            elif views:
                data[SHM_VIEWS_KEY] = views
        return msg

    def _read_ref(self, ref: dict, label: str, allow_view: bool) -> tuple[Any, bool]:
        """Прочитать один массив по ссылке ``{owner, slot, idx, gen, name}``.

        Returns ``(массив | None, это_view)``. ``None`` = перезаписано до чтения (stale) или во
        время (torn) — оба штатные дропы со счётчиком у reader'а, без лога; сегмент отвязан
        (``FileNotFoundError``) — тот же stale, счёт у middleware; сбой открытия сегмента
        (throttled лог) тоже ``None``. view (zero-copy) — только при ``allow_view`` И активном
        zero_copy (гейтнут в ctor на handle-кэш): поколение слота у view всегда сверяется с
        ``ref["gen"]`` (``frame_view_valid``), отдельной меты на провод не нужно."""
        name = ref.get("name")
        gen = ref.get("gen")
        if name and isinstance(gen, int):
            view = allow_view and self._zero_copy
            try:
                arr = self._reader.read_ref(name, gen, copy=not view)
            except FileNotFoundError:
                # 4.4c: сегмент ссылки отвязан (realloc кольца у владельца) — штатный stale-дроп, счёт
                # без лога (не ERROR на каждое сообщение, как и stale по поколению у reader'а).
                self._stale_unlinked_drops += 1
                return None, False
            except Exception as e:
                self._log_error(f"FrameShmMiddleware: чтение {label} по ссылке не удалось: {e} (shm={name})")
            else:
                if arr is not None:
                    # 4.5c: байты чтения — только успешное чтение (stale/torn → arr None → 0);
                    # единая точка для restore_frame и on_receive (оба идут через _read_ref).
                    self._add_bytes_read(int(arr.nbytes))
                return arr, (view and arr is not None)
        # Сбой открытия / битая ссылка — M2a: throttled (штатный drop после G.7, не ERROR-спам).
        self._restore_fail_count += 1
        if self._restore_fail_count == 1 or self._restore_fail_count % _RESTORE_FAIL_WARN_EVERY == 0:
            self._log_error(
                f"FrameShmMiddleware: {label} не восстановлен (drop) "
                f"({ref.get('owner')}/{ref.get('slot')}[{ref.get('idx')}], name={name or 'N/A'}; "
                f"всего={self._restore_fail_count})"
            )
        return None, False

    def _restore_refs(self, msg: dict, data: dict, refs: Any, allow_view: bool) -> Optional[list]:
        """Каждую ссылку ``_shm_refs[key]`` -> массив: ``frame`` в ``msg["frame"]``, прочие в
        ``data[key]``. Ключ, уже несущий значение (массив уехал inline), не трогается. Битая
        ссылка (не dict) — пропуск.

        Атомарность (4.4c): на ПЕРВОЙ ссылке, вернувшей ``None`` (stale/torn/сбой открытия), чтение
        останавливается, уже восстановленные ключи снимаются, возвращается ``None`` = сообщение
        отбрасывается целиком. Счётчик reader'а (``frame_stale_drops``/``frame_torn_reads``)
        растёт один раз — на ту единственную ссылку, что провалилась, т.е. считаются СООБЩЕНИЯ.
        Иначе возвращает список ссылок, восстановленных view (возможно пустой)."""
        views: list = []
        if not isinstance(refs, dict):
            return views
        restored: list = []  # (контейнер, ключ) — что снять при отбрасывании
        for key, ref in refs.items():
            if not isinstance(ref, dict):
                continue
            if key == FRAME_KEY:
                if msg.get(FRAME_KEY) is not None:
                    continue
                target = msg
            else:
                if data.get(key) is not None:
                    continue
                target = data
            arr, is_view = self._read_ref(ref, key, allow_view=allow_view)
            if arr is None:
                for container, done_key in restored:
                    container.pop(done_key, None)
                return None
            target[key] = arr
            restored.append((target, key))
            if is_view:
                views.append(ref)
        return views

    def _large_entries(self, item: dict) -> list:
        """(ключ, массив) к записи ссылкой: ``frame`` (всегда, если не None) первым, затем
        крупные ndarray прочих ключей ВЕРХНЕГО уровня (C1/C2; вложенные — вне 4.1)."""
        entries = []
        frame = item.get(FRAME_KEY)
        if frame is not None:
            entries.append((FRAME_KEY, frame))
        for key, value in item.items():
            if key != FRAME_KEY and _is_large_array(value):
                entries.append((key, value))
        return entries

    @staticmethod
    def _copy_inline_views(item: dict) -> None:
        """Заменить копиями ndarray верхнего уровня item'а с ``not flags.owndata`` (4.4d): после записи
        в кольца в item остаются только inline-значения, а те из них, что смотрят в память чужого слота
        (срез view), роутер сериализует после двери. Вложенные структуры не трогаются (см. остаток в
        ``strip_and_write``)."""
        from numpy import ndarray

        for key, value in list(item.items()):
            if isinstance(value, ndarray) and not value.flags.owndata:
                item[key] = value.copy()

    def strip_and_write(self, item: dict) -> dict:
        """Записать frame и крупные массивы в SHM, убрать из item, добавить shm_ref.

        Task 4.1: ``frame`` — ссылкой всегда (плоские поля в item); любой другой ключ
        верхнего уровня с ndarray ``nbytes >= CLAIM_CHECK_MIN_NBYTES`` — ссылкой в
        ``item["_shm_refs"][key]`` (своё кольцо на ключ, ``_write_item_arrays``). Мельче —
        inline, не трогается. Fallback: SHM write не удался (mm есть) — массив остаётся в
        item и идёт pickle; это ГРОМКО (``frame_pickle_fallbacks``, G.3d). mm=None —
        pickle-by-design, не деградация. Исчерпание займа на любом кольце — drop всего
        сообщения (``_last_loan_exhausted``; дропает send-middleware).

        Дверь отправки (Task 4.4 / 4.4d). Если item несёт ``_shm_views`` (входы — zero-copy view на
        чужие слоты) и mm есть — ПОСЛЕ записи в кольца и ДО возврата: (1) каждый оставшийся в item
        ndarray верхнего уровня с ``not flags.owndata`` (малый срез view, 1D/4D, не-native dtype,
        fallback-массив) заменяется копией — иначе он сериализуется роутером уже ПОСЛЕ двери, а слот
        источника за это время перезаписывается; (2) ``_inputs_still_valid`` — перезаписанный вход
        помечает item ``_shm_dropped`` (дроп всех целей, один раз на item). Проверка идёт и в ветке
        БЕЗ крупных массивов. Известный остаток: массивы во ВЛОЖЕННЫХ list/dict не копируются и
        дверь их не защищает.

        Fan-out (F1, ревью 2026-07-13): producer переиспользует ОДИН item-dict для
        нескольких targets — первый вызов стрипает массивы (→ SHM), второй и далее видят
        уже стрипнутый item (массивов нет, ссылки проставлены). Это ВСЁ РАВНО реальный
        отдельный IPC-send — агрегатный счётчик границ считает его, ``frame_hops`` НЕ
        задваивает, повторной записи нет (C6).

        Returns:
            item без массивов (+ shm_ref) или item с массивами (fallback).
        """
        self._last_loan_exhausted = False
        if item.get(SHM_DROPPED_KEY):
            return item  # fan-out повтор уже отброшенного item'а — дропает strip_data_frame_on_send
        if self._has_own_ref(item):
            # Fan-out replay — тот же item уже стрипнут для другого target.
            self._bump_boundary_only()
            return item
        entries = self._large_entries(item)
        has_views = bool(item.get(SHM_VIEWS_KEY))
        if entries and self._mm is not None:
            self._write_item_arrays(item, entries)
            # Ф7 G.6: item реально уходит через IPC в другой процесс (SHM-успех ИЛИ
            # pickle-fallback — оба пути кладут item на исходящий транспорт).
            self._bump_frame_hops(item)
            if self._last_loan_exhausted:
                return item  # дропнется целиком; входные ссылки нужны повторной попытке
        else:
            # mm=None -> pickle-by-design (массивы остаются в item), не деградация.
            item.pop(SHM_REFS_KEY, None)
            if entries:
                self._bump_frame_hops(item)
        if has_views and self._mm is not None:
            # copy-then-check (4.4d): сначала копии inline-срезов view, потом проверка входов.
            self._copy_inline_views(item)
            if not self._inputs_still_valid(item):
                item[SHM_DROPPED_KEY] = True
                return item
        # Один хоп: унаследованные ссылки (owner != self) уже заменены своими, локальная мета
        # view с провода снимается.
        item.pop(SHM_VIEWS_KEY, None)
        return item

    @staticmethod
    def _shape_hwc(frame: Any) -> tuple[int, int, int]:
        """Нормализовать форму кадра к (h, w, c). Grayscale (H, W) → (H, W, 1)."""
        sh = frame.shape
        if len(sh) == 2:
            return int(sh[0]), int(sh[1]), 1
        return int(sh[0]), int(sh[1]), int(sh[2])

    def strip_data_frame_on_send(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send-middleware для data-pipeline (P3.1.2): вынести frame из msg["data"] в SHM.

        Регистрируется через ``RouterManager.add_send_middleware`` в GenericProcess —
        Claim Check кадров становится делом хаба, а не явного вызова в
        SourceProducer/PipelineExecutor. Использует generic-семантику
        :meth:`strip_and_write` (lazy-alloc, round-robin ring, pickle-fallback) поверх
        ``msg["data"]`` (item остаётся тем же dict — мутируется на месте).

        Срабатывает ТОЛЬКО на data-сообщениях (``type=="data"``) — команды/heartbeat/
        state проходят без изменений (быстрый guard, ноль накладных на не-кадровых
        сообщениях). Путь top-level-frame (`wire.configure` → on_send) не
        затрагивается: там frame в ``msg["frame"]``, а не в ``msg["data"]``.

        Fan-out (F1, ревью 2026-07-13): producer переиспользует один item для
        нескольких targets; первый ``router.send`` стрипает его (frame → SHM,
        координаты в data), последующие видят item уже без frame. ``strip_and_write``
        зовётся на КАЖДЫЙ send (не только пока в data есть "frame") — сам решает,
        первый это стрип (пишет в SHM) или fan-out-повтор (только считает границу).
        """
        if msg.get("type") != "data":
            return msg
        data = msg.get("data")
        if isinstance(data, dict):
            self.strip_and_write(data)
            # Ф7 G.5.d (В3): исчерпание free-list → DROP-на-источнике (send не уходит).
            # None из send-middleware = router дропает отправку (middleware_dropped).
            if self._last_loan_exhausted:
                return None
            # Task 4.4: вход был перезаписан, пока копировали (дверь отправки) -> дроп ВСЕХ целей:
            # метка живёт на item'е, повтор fan-out видит её и тоже возвращает None.
            if data.get(SHM_DROPPED_KEY):
                return None
        return msg

    # ------------------------------------------------------------------
    # RouterManager middleware-протокол: on_send / on_receive
    # ------------------------------------------------------------------

    def _drop_foreign_refs(self, data: Any) -> None:
        """Снять из ``data["_shm_refs"]`` ссылки с ``owner != self._owner`` (4.4d); опустевший ключ
        удаляется. Не dict / нет ссылок — no-op."""
        refs = data.get(SHM_REFS_KEY) if isinstance(data, dict) else None
        if not isinstance(refs, dict):
            return
        own = {k: r for k, r in refs.items() if isinstance(r, dict) and r.get("owner") == self._owner}
        if len(own) == len(refs):
            return
        if own:
            data[SHM_REFS_KEY] = own
        else:
            data.pop(SHM_REFS_KEY, None)

    def on_send(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить исходящее сообщение: записать frame в SHM, заменить на координаты.

        Ф7 G.3a: запись делегирована в единое ядро `_write_frame_into_slot`
        (round-robin вместо снятого find_free_index). Сбой write (mm есть) →
        громкий pickle-fallback (G.3d). frame берётся из top-level ``msg["frame"]``,
        ссылка кладётся в ``msg["data"]["_shm_refs"]["frame"]`` (форма — в заголовке слота).

        Если в msg нет ключа "frame" — либо это вообще не кадровое сообщение (нет
        "data" или в нём нет shm-маркера — не трогаем, ноль накладных), либо frame
        уже стрипнут раньше для другого send этого же msg (fan-out replay, F1
        ревью 2026-07-13: считаем границу ЕЩЁ РАЗ — это реальный отдельный IPC-send). Ссылки чужого
        владельца (``owner != self._owner``) на этом пути снимаются — один хоп (4.4d): ссылка деда
        не должна ехать дальше.
        """
        frame = msg.get("frame")
        if frame is None:
            # Дизъюнктность путей (пост-фикс ревью 2026-07-13): data-сообщения —
            # зона ответственности strip_data_frame_on_send (он их уже считает);
            # если оба middleware зарегистрированы на одном роутере, replay-ветка
            # без этого guard'а посчитала бы ту же отправку ВТОРОЙ раз.
            if msg.get("type") == "data":
                return msg
            existing_data = msg.get("data")
            if self._has_own_ref(existing_data):
                self._bump_boundary_only()
            self._drop_foreign_refs(existing_data)
            return msg

        # Проверка что это numpy ndarray (без жёсткого импорта numpy на уровне модуля)
        if not hasattr(frame, "shape"):
            return msg

        # F4 (ревью 2026-07-13): msg["data"] мог существовать, но быть НЕ dict
        # (например None) — setdefault тогда вернул бы этот None, и .get()/[] ниже
        # упали бы AttributeError'ом (кадр молча тихо ехал бы pickle — тихая
        # деградация, чего это поле как раз должно избегать).
        data = msg.get("data")
        if not isinstance(data, dict):
            data = {}
            msg["data"] = data

        # Ф7 G.6: с этой точки кадр гарантированно уходит через IPC — либо SHM-ref
        # (успех записи ниже), либо pickle (msg["frame"] остаётся, если mm недоступен
        # или запись не удалась). Считаем границу ДО ветвления по исходу.
        self._bump_frame_hops(data)

        if self._mm is None:
            return msg  # pickle-by-design (SHM не сконфигурирован)

        ref: Dict[str, Any] = {}
        if not self._write_frame_into_slot(frame, ref):
            # Ф7 G.5.d (В3): исчерпание free-list → DROP-на-источнике (None = дроп send),
            # НЕ pickle-fallback.
            if self._last_loan_exhausted:
                return None
            # mm есть, но write не удался → громкий pickle-fallback (G.3d).
            self._note_pickle_fallback("on_send")
            return msg

        # Убрать frame из сообщения (не передавать numpy через IPC). Task 4.4: ссылка — в том же
        # формате, что и на generic-пути (``data["_shm_refs"]["frame"]``, только СВОИ ссылки);
        # ``width``/``height`` больше не пишутся — форма едет в заголовке слота.
        msg.pop("frame", None)
        data[SHM_REFS_KEY] = {FRAME_KEY: ref}

        return msg

    def on_receive(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить входящее сообщение: прочитать frame из SHM по координатам.

        Если msg["data"] не содержит SHM-координат — пропускает без изменений.

        Task 4.4: ВСЕ ссылки (``frame`` -> ``msg["frame"]``, прочие -> ``data[key]``) читаются
        КОПИЕЙ (copy-out потребитель release не шлёт) по ``ref["name"]`` со сверкой поколения
        ``ref["gen"]``: перезаписанная ячейка -> ``None`` + ``frame_stale_drops``, рваное чтение ->
        ``None`` + ``frame_torn_reads``.

        Атомарность (4.4c): нечитаемая ссылка любого ключа -> ``None`` из middleware (RouterManager
        считает это ``middleware_dropped`` и сообщение не доставляет) — потребитель не увидит ни
        ``frame`` без ``mask``, ни ключ со значением ``None``.
        """
        data = msg.get("data")
        if not isinstance(data, dict):
            return msg
        refs = data.get(SHM_REFS_KEY)
        if refs and self._restore_refs(msg, data, refs, allow_view=False) is None:
            return None  # 4.4c: одна нечитаемая ссылка -> сообщение отбрасывается целиком (drop у router'а)
        return msg
