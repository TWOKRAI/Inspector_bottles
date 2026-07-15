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

**Ф7 G.3 (b) — seqlock.** Слот SHM может быть в seqlock-формате (ADR-SRM-011). Флаг
формата едет в сообщении полем `shm_seqlock` (Dict at Boundary) — cross-process reader
(`FrameReader.read_frame`, H-задача) сверяет generation и дропает torn/in-progress кадр.

**Ф7 G.3 (d) — громкий pickle-fallback.** Сбой SHM-write (mm есть, но запись не удалась)
→ кадр уходит pickle-через-Queue (×3 латентность). Раньше — молча. Теперь: счётчик
`frame_pickle_fallbacks` (агрегируется в `RouterManager.get_stats`) + throttled WARNING.

**Ф7 G.3 (кэш handles) / H-задача Этап 2.** Cross-process raw-чтение открывало SharedMemory
на каждый кадр (open/mmap/close + resource_tracker). Кэш handles + zero-copy view + post-use
re-check вынесены за фасад `FrameReader` (модуль памяти); транспорт держит reader через DI и
делегирует (`read_frame`/`view_valid`/`close_handle_cache`), синхронизация — внутри reader'а.

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

import logging
from typing import Any, Callable, Dict, Optional

# Размер LRU-кэша SHM-handles читателя (обычно 1–3 живых имени; запас на realloc/switch).
_HANDLE_CACHE_CAP = 8
# Throttle громкого WARNING про pickle-fallback (счётчик — всегда, лог — раз в N кадров).
_PICKLE_WARN_EVERY = 300
# Throttle лога «frame не восстановлен» (штатный drop после G.7 — не ERROR на каждый кадр).
_RESTORE_FAIL_WARN_EVERY = 300


class FrameShmMiddleware:
    """Middleware для frame ↔ SHM на границах процессов.

    Args:
        memory_manager: MemoryManager из shared_resources_module (API write_images/
            read_images/find_free_index/create_memory_dict). Может быть ``None`` —
            запись деградирует в pickle-fallback (кадр остаётся в сообщении), но
            middleware всё равно должен быть зарегистрирован (Ф7 G.6 ревью, F3):
            иначе счётчик границ на этом пути не считает вовсе.
        owner: имя процесса-владельца SHM-региона (для write).
        slot: имя SHM-слота (для write).
        coll: количество SHM-слотов (размер ring buffer) — generic-путь.
        log_error: callback логирования ошибок — generic-путь.
        cache_shm_handles: кэшировать SHM-handles читателя (Ф7 G.3). None → env
            ``FW_SHM_HANDLE_CACHE`` → False (прежний open/close на кадр).

    Формат слота seqlock (Ф7 G.3b) middleware НЕ решает сам, а СЧИТЫВАЕТ у слота
    после аллокации (``MemoryManager.get_memory_data(...)["seqlock"]``) и кладёт
    авторитетно в сообщение как ``shm_seqlock`` — иначе флаг в сообщении мог бы
    разойтись с реальным форматом слота (writer в seqlock, сообщение говорит нет →
    reader читает не с того offset). Флаг слота задаёт сам MemoryManager
    (``seqlock_frames`` ctor > env ``FW_SHM_SEQLOCK``, ADR-SRM-011).

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
        # M2c: torn/дропнутые cross-process seqlock-чтения (raw-путь middleware —
        # manager считает свои, но raw-путь его не проходит). Агрегируется в get_stats.
        self.frame_torn_reads = 0
        # Ф7 G.5.c: post-use re-check zero-copy view — слот перезаписан под живым view.
        # H-задача (Этап 2): счётчик теперь у reader'а (`self._reader.stale_drops`),
        # frame_stale_drops — read-only property (агрегируется в get_stats → heartbeat).
        # M2d: причина последнего сбоя записи — для громкого fallback-лога.
        self._last_write_error = ""
        # M2a: троттлинг «frame не восстановлен» (штатный drop после G.7, не ERROR-спам).
        self._restore_fail_count = 0
        self._allocated = False
        # H5b: создал ли слот САМ этот middleware (create_memory_dict) или ПРИНЯЛ чужой
        # (adopt PM-памяти). release_owned_memory освобождает только СВОЁ — иначе
        # deconfigure снёс бы PM-память (created==1 через configure/deconfigure-циклы).
        self._created_slot = False
        self._write_index = 0
        # Текущая ВЫДЕЛЕННАЯ ёмкость слота (h, w, c). None — ещё не выделяли.
        # Нужна для переаллокации при росте кадра (resize): иначе кадр больше блока
        # не влезает → write_images падает → вечный pickle-fallback (медленно).
        self._alloc_shape: tuple[int, int, int] | None = None
        self._alloc_dtype: str | None = None
        # Ф7 G.3(b): формат seqlock ФАКТИЧЕСКОГО слота (считывается у mm после
        # аллокации, НЕ решается middleware) → авторитетно едет в shm_seqlock.
        self._slot_seqlock = False
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
        # H-ревью (E2): транзитный кэш handles на время ОДНОГО release(): все тикеты пачки
        # одного owner/slot → memory-data dict строим раз, а не на каждый тикет.
        self._release_handles_cache: Optional[Any] = None
        # Пул владения слотами (тип: FramePool). None при выключенном loan-протоколе.
        # DI (H-ревью 2026-07-14): инжектированный ``pool`` выигрывает (подмена на
        # Rust/iceoryx2 под тем же ``FramePool`` не трогает транспорт); None + флаг →
        # дефолт-фабрика ``LoanLedger``; None + флаг off → пул=None (слепой round-robin).
        self._pool: Optional[Any] = pool
        if self._pool is None and self._loan_protocol and self._num_consumers > 0:
            # Import runtime-local (как format-хелперы) — coupling router→shared_resources
            # остаётся runtime, не top-level. gen_reader = чтение поколения СВОЕГО слота
            # (seqlock) → пул SHM-агностичен (не знает про формат слота).
            from ...shared_resources_module.memory.pool import LoanLedger

            self._pool = LoanLedger(self._coll, gen_reader=self._read_own_slot_generation)
            # Ф7 G.7: num_consumers проведён из топологии (число loan-aware целей владельца,
            # copy-out/GUI исключены — см. связку выше). Пул создаётся только при >0, поэтому
            # исчерпание из-за GUI-only fan-out (резидуал G.5) больше не воспроизводится.

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
        return self._pool.snapshot_stats()["loan_exhausted"] if self._pool else 0

    @property
    def frame_slots_released(self) -> int:
        """Слотов освобождено release'ами (здоровье loan-цикла)."""
        return self._pool.snapshot_stats()["slots_released"] if self._pool else 0

    @property
    def frame_slots_reclaimed(self) -> int:
        """Займов реклеймлено после смерти читателя (kill-9 без release)."""
        return self._pool.snapshot_stats()["slots_reclaimed"] if self._pool else 0

    @property
    def frame_stale_drops(self) -> int:
        """Ф7 H-задача (Этап 2): zero-copy view'ов дропнуто post-use re-check'ом —
        read-only проекция счётчика reader'а (единственный источник)."""
        return self._reader.stale_drops

    @staticmethod
    def _resolve_bool_flag(explicit: Optional[bool], env_name: str) -> bool:
        """Разрешить булев флаг: ctor (не None) > env ``env_name`` (в т.ч. ``=0``) > False."""
        if explicit is not None:
            return bool(explicit)
        from ...config_module.tools.env import env_flag

        return env_flag(env_name, default=False)

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
        """
        if self._mm is None or not self._allocated or not self._created_slot:
            return
        try:
            self._mm.close_memory(self._owner, self._slot)
        except Exception as exc:  # noqa: BLE001 — teardown не критичен
            self._log_error(f"FrameShmMiddleware: release_owned_memory failed: {exc}")
        self._allocated = False
        self._created_slot = False
        self._alloc_shape = None
        self._alloc_dtype = None

    def frame_view_valid(self, shm_view_name: str, gen_at_read: int) -> bool:
        """Ф7 G.5.c — post-use re-check: жив ли ещё zero-copy view (слот не перезаписан).

        Делегирует в `FrameReader.view_valid` (H-задача, Этап 2). Публичный контракт для
        `PipelineExecutor` (сверка ПОСЛЕ обработки цепочки): совпало поколение → view
        валиден; разошлось / handle эвиктнут / gen<0 → drop (счётчик ``frame_stale_drops``
        у reader'а), НЕ порча. Синхронизация — внутри reader'а (свой lock)."""
        return self._reader.view_valid(shm_view_name, gen_at_read)

    # ------------------------------------------------------------------
    # Единое ядро записи кадра в SHM (Ф7 G.3a — канон generic)
    # ------------------------------------------------------------------

    def _write_frame_into_slot(self, frame: Any, dest: Dict[str, Any]) -> bool:
        """Записать кадр в SHM-слот и вписать координаты В ``dest`` (тот же dict, что
        уезжает по IPC). M3: НЕ создаём новый dict на кадр (per-frame путь без лишних
        аллокаций — правило G.9).

        Единое ядро для strip_and_write И on_send (Ф7 G.3a): lazy-alloc + realloc при
        росте кадра + round-robin по слотам. Формат слота (seqlock) применяет
        MemoryManager по стампу; в ``dest`` едет только флаг ``shm_seqlock`` (для
        cross-process reader).

        Returns:
            True — записано в SHM, координаты в ``dest``; False — mm отсутствует или
            write не удался (причина в ``self._last_write_error`` для громкого лога).
        """
        self._last_loan_exhausted = False
        if self._mm is None:
            self._last_write_error = "memory_manager=None"
            return False

        # Lazy allocation при первом кадре + ПЕРЕАЛЛОКАЦИЯ при росте кадра (resize).
        if not self._allocated or not self._frame_fits(frame):
            self._allocate_shm(frame)

        idx = self._acquire_slot()
        if idx is None:
            return False  # loan-исчерпание (drop-на-источнике; счётчик — в _acquire_slot)
        if self._write_and_publish(frame, idx, dest):
            return True
        # Ф7 H-ревью: write не удался → ОТМЕНИТЬ loan (WRITING→FREE), иначе зарезервированный
        # acquire'ом слот утёк бы навсегда (ёмкость кольца тает). loan↔publish/abort (iceoryx2).
        if self._pool is not None:
            self._pool.abort(idx)
        return False

    def _acquire_slot(self) -> Optional[int]:
        """Ф7 G.5.d (В3): выбор индекса слота. loan-протокол — СВОБОДНЫЙ слот из free-list
        (``acquire`` резервирует WRITING); нет свободных → None + громкий drop-на-источнике
        (не write-fail). off → прежний слепой round-robin (бит-в-бит)."""
        if self._pool is not None:
            idx = self._pool.acquire()
            if idx is None:
                self._note_loan_exhausted()
            return idx
        idx = self._write_index % self._coll
        self._write_index += 1
        return idx

    def _write_and_publish(self, frame: Any, idx: int, dest: Dict[str, Any]) -> bool:
        """Записать кадр в слот ``idx`` и (при loan) опубликовать (commit); координаты → ``dest``.

        True — записано (dest заполнен); False — write не удался (причина в
        ``_last_write_error``; вызывающий отменит loan через ``abort``)."""
        try:
            shm_name = self._mm.write_images(self._owner, self._slot, [frame], idx)
            if shm_name:
                if self._pool is not None:
                    # loan/publish: слот занят num_consumers читателями; release (d-2) → 0.
                    self._pool.commit(idx, self._num_consumers)
                dest["owner"] = self._owner
                dest["shm_owner"] = self._owner
                dest["shm_name"] = self._slot
                dest["shm_index"] = idx
                dest["shm_actual_name"] = shm_name
                dest["shm_seqlock"] = self._slot_seqlock
                return True
            self._last_write_error = "write_images вернул None (нет слота/валидация)"
        except Exception as exc:  # noqa: BLE001 — причина едет в громкий лог (M2d)
            self._last_write_error = repr(exc)
        return False

    def _note_loan_exhausted(self) -> None:
        """Ф7 G.5.d (В3): free-list исчерпан → back-pressure = ГРОМКИЙ drop-на-источнике
        (кадр не уходит; счётчик всегда, WARNING throttled). Живую камеру НЕ блокируем.

        Ф7 H-задача: счётчик инкрементит пул внутри ``acquire()`` (при None); здесь —
        только per-write сигнал + throttled лог (читаем актуальное число из пула)."""
        self._last_loan_exhausted = True
        n = self.frame_loan_exhausted
        if n == 1 or n % _PICKLE_WARN_EVERY == 0:
            self._log_error(
                f"FrameShmMiddleware: free-list исчерпан (читатели отстали), кадр дропнут "
                f"на источнике [owner={self._owner}/{self._slot}; глубина={self._coll}; "
                f"всего={n}]"
            )

    def _read_own_slot_generation(self, idx: int) -> int:
        """Ф7 G.5.d-2: прочитать ТЕКУЩЕЕ поколение СВОЕГО слота (owner-side) — для
        generation-guard на release. Под займом (refcount>0) writer слот не трогает,
        поэтому поколение стабильно = то, что прочитал consumer. -1 при недоступности.

        H-ревью (E2): при release пачки handles уже сняты ОДИН раз (release_slots →
        ``_release_handles_cache``) — не пересобираем memory-data dict на КАЖДЫЙ тикет."""
        try:
            handles = self._release_handles_cache
            if handles is None:
                md = self._mm.get_memory_data(self._owner, self._slot) if self._mm else None
                handles = md.get("handles") if md else None
            if handles and 0 <= idx < len(handles) and handles[idx] is not None:
                from ...shared_resources_module.memory.format import read_generation

                return read_generation(handles[idx].buf)
        except Exception:
            pass
        return -1

    def release_slots(self, releases: list) -> None:
        """Ф7 G.5.d-2 (В3): owner-side release-handler — тонкий адаптер к пулу (H-задача).

        Consumer, дочитав view, шлёт пачку тикетов ``{index, generation, reader}``;
        транспорт делегирует декремент refcount в ``FramePool.release`` (guard'ы —
        refcount==0/stale generation/dup reader — внутри пула; generation читается
        инжектированным ``gen_reader`` = ``_read_own_slot_generation``). refcount мутирует
        ТОЛЬКО этот (owner) процесс. Любая ошибка учёта безопасна: В1 re-check ловит
        преждевременное освобождение (writer перезапишет → drift → drop, не corruption).
        """
        if self._pool is None or not releases:
            return
        # H-ревью (E2): снять handles ОДИН раз на пачку — gen_reader читает из кэша, не
        # пересобирает memory-data dict на каждый тикет. finally гарантирует сброс кэша.
        try:
            md = self._mm.get_memory_data(self._owner, self._slot) if self._mm else None
            self._release_handles_cache = md.get("handles") if md else None
            self._pool.release(releases)
        finally:
            self._release_handles_cache = None

    def reclaim_reader(self, dead_reader: str) -> int:
        """Ф7 G.5.e (В3): реклейм займов МЁРТВОГО читателя (kill-9 без release) — адаптер.

        При fan-out мёртвый reader держал все слоты, которые ещё НЕ отпустил → пул
        декрементит за него (тот же учёт, инициатор — владелец по confirmed-death
        соседа: supervisor/incarnation). Идемпотентно (повторный вызов после реклейма →
        0). Транспорт делегирует в ``FramePool.reclaim`` и лишь ГРОМКО логирует результат
        (логирование — дело транспорта-владельца, у пула логгера нет). Вторая линия —
        startup-cleanup осиротевших сегментов G.3(c); В1 re-check ловит любую ошибку
        учёта. Возвращает число реклеймленных займов."""
        if self._pool is None or not dead_reader:
            return 0
        reclaimed = self._pool.reclaim(dead_reader)
        if reclaimed:
            self._log_error(
                f"FrameShmMiddleware: реклейм {reclaimed} займов мёртвого читателя "
                f"'{dead_reader}' [owner={self._owner}/{self._slot}]"
            )
        return reclaimed

    # ------------------------------------------------------------------
    # Generic data-pipeline API (канон): strip_and_write / restore_frame
    # ------------------------------------------------------------------

    def restore_frame(self, msg: dict) -> dict:
        """Восстановить frame из SHM ref в item.

        Входящий msg содержит shm_name, shm_index (или owner + slot + index).
        Читает ndarray из SHM → кладёт в msg["frame"].

        Стратегия:
          1. MemoryManager.read_images() — если SHM handle есть в этом процессе
          2. Fallback: прямое открытие SharedMemory по shm_actual_name (cross-process)
        """
        data = msg.get("data", msg)

        # Pickle fallback: frame уже в сообщении (не через SHM)
        if "frame" in msg and msg["frame"] is not None:
            return msg
        if "frame" in data and data.get("frame") is not None:
            msg["frame"] = data["frame"]
            return msg

        shm_owner = data.get("owner", data.get("shm_owner", ""))
        shm_name = data.get("shm_name", "")
        shm_index = data.get("shm_index", 0)

        if not shm_owner or not shm_name:
            return msg

        # Попытка 1: через MemoryManager (работает в пределах одного процесса; знает
        # seqlock-формат из своей меты слота, сам дропает torn → None).
        try:
            images = self._mm.read_images(shm_owner, shm_name, shm_index, n=1)
            if images:
                msg["frame"] = images[0]
                return msg
        except Exception:
            pass

        # Попытка 2: прямое открытие SharedMemory по shm_actual_name (cross-process).
        # Флаг seqlock едет в сообщении (Dict at Boundary) — reader сверяет generation.
        shm_actual_name = data.get("shm_actual_name")
        if shm_actual_name:
            seqlock = bool(data.get("shm_seqlock", False))
            # Ф7 G.5.b: zero-copy view вместо .copy() — только при активном zero_copy
            # (уже гейтнут на handle-кэш в ctor) И seqlock (read-moment torn-защита +
            # generation для post-use re-check G.5.c). Без seqlock — копия (нет защиты).
            view = self._zero_copy and seqlock
            try:
                frame = self._reader.read_frame(
                    shm_actual_name,
                    seqlock=seqlock,
                    copy=not view,
                    view_meta=data if view else None,
                )
                if frame is not None:
                    msg["frame"] = frame
                    return msg
                # M2c: None при seqlock = torn/in-progress → ШТАТНЫЙ drop (счётчик, не лог).
                if seqlock:
                    self.frame_torn_reads += 1
                    msg["frame"] = None
                    return msg
            except Exception as e:
                self._log_error(f"FrameShmMiddleware(generic): SHM fallback failed: {e} (shm={shm_actual_name})")

        # Обе попытки не сработали (не seqlock-torn) — M2a: throttled (после G.7 иначе
        # ERROR на каждый дропнутый кадр), это штатный drop, не критичная ошибка.
        msg["frame"] = None
        self._restore_fail_count += 1
        if self._restore_fail_count == 1 or self._restore_fail_count % _RESTORE_FAIL_WARN_EVERY == 0:
            self._log_error(
                f"FrameShmMiddleware(generic): frame не восстановлен (drop) "
                f"({shm_owner}/{shm_name}[{shm_index}], "
                f"actual={data.get('shm_actual_name', 'N/A')}; всего={self._restore_fail_count})"
            )
        return msg

    def strip_and_write(self, item: dict) -> dict:
        """Записать frame в SHM, убрать из item, добавить shm_ref.

        Делегирует запись в единое ядро `_write_frame_into_slot` (Ф7 G.3a). Fallback:
        если SHM write не удался (mm есть, но write failed) — frame остаётся в item и
        пойдёт через pickle в IPC; это ГРОМКО (счётчик frame_pickle_fallbacks, G.3d).
        mm=None (SHM не сконфигурирован) — pickle-by-design, не считается деградацией.

        Fan-out (F1, ревью 2026-07-13): producer переиспользует ОДИН item-dict для
        нескольких targets — первый вызов стрипает frame (пиксели → SHM), второй и
        далее видят уже стрипнутый item (frame=None, shm_name уже проставлен). Это
        ВСЁ РАВНО реальный отдельный IPC-send (другому target) — агрегатный
        счётчик границ считает его, per-item поле ``frame_hops`` НЕ задваивает.

        Returns:
            item без "frame" (+ shm_ref) или item с "frame" (fallback).
        """
        frame = item.get("frame")
        if frame is None:
            if item.get("shm_name"):
                # Fan-out replay — тот же item уже стрипнут для другого target.
                self._bump_boundary_only()
            return item

        if self._mm is not None:
            if self._write_frame_into_slot(frame, item):
                # SHM write OK — координаты уже в item, убрать frame.
                item.pop("frame", None)
            elif not self._last_loan_exhausted:
                # mm есть, write не удался (НЕ исчерпание loan) → громкий pickle-fallback
                # (G.3d). При исчерпании loan (В3) — это DROP, а не fallback: кадр не
                # уходит; drop выполняет send-middleware (strip_data_frame_on_send → None).
                self._note_pickle_fallback("strip_and_write")
        # mm=None → pickle-by-design (frame остаётся в item), не деградация.

        # Ф7 G.6: item реально уходит через IPC в другой процесс (SHM-успех ИЛИ
        # pickle-fallback — оба пути кладут item на исходящий транспорт).
        self._bump_frame_hops(item)

        return item

    @staticmethod
    def _shape_hwc(frame: Any) -> tuple[int, int, int]:
        """Нормализовать форму кадра к (h, w, c). Grayscale (H, W) → (H, W, 1)."""
        sh = frame.shape
        if len(sh) == 2:
            return int(sh[0]), int(sh[1]), 1
        return int(sh[0]), int(sh[1]), int(sh[2])

    def _frame_fits(self, frame: Any) -> bool:
        """Влезает ли кадр в текущую выделенную ёмкость (по каждому измерению + dtype)."""
        if self._alloc_shape is None:
            return False
        fh, fw, fc = self._shape_hwc(frame)
        ah, aw, ac = self._alloc_shape
        return fh <= ah and fw <= aw and fc <= ac and str(frame.dtype) == self._alloc_dtype

    def _allocate_shm(self, frame: Any) -> None:
        """(Пере)выделить SHM-блоки под кадр. Grow-only: ёмкость только растёт.

        Целевая форма = max(текущая_ёмкость, форма_кадра) по каждому измерению —
        блок не сжимается (меньшие кадры читаются по header), но растёт под бо́льшие.
        Растёт ограниченное число раз (до максимума кадра камеры) → сходится, без
        thrash. При переаллокации старый блок закрывается (owner → unlink), новый
        создаётся; новый shm_actual_name едет в каждом сообщении → читатели следуют.
        """
        try:
            fh, fw, fc = self._shape_hwc(frame)
            dtype = str(frame.dtype)
            # H5a: adopt-if-exists — PM в wire_setup мог УЖЕ создать (owner, slot).
            # Свежий middleware (wire.configure, _allocated=False) создал бы ВТОРОЙ раз,
            # осиротив первый handle. Если mm уже держит слот — принять как выделенный
            # (grow-only ниже пересоздаст лишь при росте кадра).
            if not self._allocated:
                self._adopt_existing_slot_if_any()
            # Grow-only: не уменьшаем ёмкость (избегаем «качелей» при чередовании размеров).
            if self._alloc_shape is not None and dtype == self._alloc_dtype:
                ah, aw, ac = self._alloc_shape
                target = (max(ah, fh), max(aw, fw), max(ac, fc))
            else:
                target = (fh, fw, fc)

            # Уже выделено и форма не меняется — ничего не делаем (defensive).
            if self._allocated and target == self._alloc_shape and dtype == self._alloc_dtype:
                return

            # Переаллокация: закрыть старый блок (owner → unlink), затем создать новый.
            if self._allocated:
                try:
                    self._mm.close_memory(self._owner, self._slot)
                except Exception as e:
                    self._log_error(f"FrameShmMiddleware: close old SHM before realloc: {e}")

            memory_names = {self._slot: (1, target, dtype)}
            self._mm.create_memory_dict(self._owner, memory_names, self._coll)
            self._allocated = True
            self._created_slot = True  # H5b: слот создан ЭТИМ middleware → он его и освободит
            self._alloc_shape = target
            self._alloc_dtype = dtype
            self._write_index = 0  # свежие слоты — пишем с начала кольца
            # Ф7 G.5.d (В3): свежее кольцо (старые сегменты unlink'нуты) → free-list
            # сбрасывается в «всё свободно»; старые займы void (сегменты ушли, читатели
            # инвалидируют кэш по incarnation, В1 re-check дропнет). H-задача: reset у пула.
            if self._pool is not None:
                self._pool.reset()
            # Ф7 G.3(b): считать ФАКТИЧЕСКИЙ формат слота (seqlock задаёт mm) —
            # авторитетный источник для shm_seqlock в сообщении.
            try:
                md = self._mm.get_memory_data(self._owner, self._slot)
                self._slot_seqlock = bool(md.get("seqlock", False)) if md else False
            except Exception:
                self._slot_seqlock = False
        except Exception as e:
            self._log_error(f"FrameShmMiddleware: allocate SHM error: {e}")

    def _adopt_existing_slot_if_any(self) -> None:
        """H5a: если mm уже держит (owner, slot) — принять как выделенный, не создавать
        второй раз. Grow-only realloc в _allocate_shm пересоздаст лишь при росте кадра.
        """
        try:
            md = self._mm.get_memory_data(self._owner, self._slot)
        except Exception:
            return
        params = md.get("params", {}).get(self._slot) if md else None
        if not params:
            return
        _, existing_shape, existing_dtype = params
        self._allocated = True
        self._created_slot = False  # H5b: принят чужой слот (PM) — release его не трогает
        self._alloc_shape = tuple(existing_shape)  # type: ignore[assignment]
        self._alloc_dtype = str(existing_dtype)
        self._slot_seqlock = bool(md.get("seqlock", False))

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
        return msg

    # ------------------------------------------------------------------
    # RouterManager middleware-протокол: on_send / on_receive
    # ------------------------------------------------------------------

    def on_send(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить исходящее сообщение: записать frame в SHM, заменить на координаты.

        Ф7 G.3a: запись делегирована в единое ядро `_write_frame_into_slot`
        (round-robin вместо снятого find_free_index). Сбой write (mm есть) →
        громкий pickle-fallback (G.3d). frame берётся из top-level ``msg["frame"]``,
        координаты кладутся в ``msg["data"]`` (+ width/height для back-compat).

        Если в msg нет ключа "frame" — либо это вообще не кадровое сообщение (нет
        "data" или в нём нет shm-маркера — не трогаем, ноль накладных), либо frame
        уже стрипнут раньше для другого send этого же msg (fan-out replay, F1
        ревью 2026-07-13: считаем границу ЕЩЁ РАЗ — это реальный отдельный IPC-send).
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
            if isinstance(existing_data, dict) and existing_data.get("shm_name"):
                self._bump_boundary_only()
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

        if not self._write_frame_into_slot(frame, data):
            # Ф7 G.5.d (В3): исчерпание free-list → DROP-на-источнике (None = дроп send),
            # НЕ pickle-fallback.
            if self._last_loan_exhausted:
                return None
            # mm есть, но write не удался → громкий pickle-fallback (G.3d).
            self._note_pickle_fallback("on_send")
            return msg

        # Убрать frame из сообщения (не передавать numpy через IPC). Координаты слота
        # уже в data (M3). width/height — back-compat поля для старых читателей.
        msg.pop("frame", None)
        data["width"] = frame.shape[1]
        data["height"] = frame.shape[0]

        return msg

    def on_receive(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить входящее сообщение: прочитать frame из SHM по координатам.

        Если msg["data"] не содержит SHM-координат — пропускает без изменений.

        Стратегия чтения (приоритет):
          1. MemoryManager.read_images() с координатами из сообщения
          2. Прямое открытие SharedMemory по shm_actual_name (другой OS-процесс),
             seqlock-флаг из сообщения (Ф7 G.3b) → reader дропает torn.
        """
        data = msg.get("data")
        if not isinstance(data, dict):
            return msg

        shm_name = data.get("shm_name")
        shm_index = data.get("shm_index")

        if shm_name is None or shm_index is None:
            return msg

        # Координаты из сообщения (приоритет) или конфигурация middleware (fallback)
        owner = data.get("shm_owner", self._owner)
        slot = shm_name or self._slot

        # Попытка 1: через MemoryManager (работает если handles открыты в этом процессе)
        if self._mm:
            images = self._mm.read_images(owner, slot, shm_index, n=1)
            if images:
                msg["frame"] = images[0]
                return msg

        # Попытка 2: прямое открытие SharedMemory по фактическому имени.
        shm_actual_name = data.get("shm_actual_name")
        if shm_actual_name:
            seqlock = bool(data.get("shm_seqlock", False))
            try:
                frame = self._reader.read_frame(shm_actual_name, seqlock=seqlock)
                if frame is not None:
                    msg["frame"] = frame
                elif seqlock:
                    # M2c: torn/in-progress → штатный drop (счётчик, агрегируется в get_stats).
                    self.frame_torn_reads += 1
            except Exception as exc:
                logging.getLogger("FrameShmMiddleware").warning(
                    "SHM fallback read failed: %s (shm=%s)", exc, shm_actual_name
                )

        return msg
