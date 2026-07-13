# -*- coding: utf-8 -*-
"""FrameShmMiddleware — единый middleware «frame ↔ SHM ref» (P3.1.1, ADR-COMM-003).

Слияние двух ранее дублировавшихся реализаций (§5.2 аудита):
- generic data-pipeline (`process_module/generic`): `strip_and_write`/`restore_frame`
  — lazy-allocation, round-robin ring (`% coll`), pickle-fallback при сбое SHM-write;
- router middleware (`router_module/middleware`): `on_send`/`on_receive`
  — middleware-протокол RouterManager (`add_send_middleware`/`add_receive_middleware`),
  запись по `find_free_index`, координаты в `msg["data"]` + width/height.

Канон поведения — generic (живой data-path камеры). Обе пары методов сосуществуют
(каждый вызывающий пользуется своей), общий ~30-строчный SHM-read-fallback (прямое
открытие `SharedMemory` по `shm_actual_name`) вынесен в `_read_shm_from_actual_name` —
именно он был дублём. `process_module/generic/frame_shm_middleware.py` ре-экспортирует
этот класс (direction process_module → router_module уже существует, цикла нет).

Claim Check: пиксели (numpy) едут в OS SHM, по очереди — только координаты (shm_ref).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional


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
    """

    def __init__(
        self,
        memory_manager: Any,
        owner: str,
        slot: str = "output_frames",
        coll: int = 3,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._mm = memory_manager
        self._owner = owner
        self._slot = slot
        self._coll = coll
        self._log_error = log_error or (lambda msg: None)
        # Ф7 G.6 (F5 ревью 2026-07-13): собственный счётчик, БЕЗ колбэка в
        # RouterManager (тот давал reference-cycle middleware↔router + третий lock
        # на send-пути). RouterManager сам суммирует этот атрибут у всех
        # зарегистрированных middleware в get_stats() — см. класс-докстринг.
        self.frame_boundary_crossings = 0
        self._allocated = False
        self._write_index = 0
        # Текущая ВЫДЕЛЕННАЯ ёмкость слота (h, w, c). None — ещё не выделяли.
        # Нужна для переаллокации при росте кадра (resize): иначе кадр больше блока
        # не влезает → write_images падает → вечный pickle-fallback (медленно).
        self._alloc_shape: tuple[int, int, int] | None = None
        self._alloc_dtype: str | None = None

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

    # ------------------------------------------------------------------
    # Общий SHM-read-fallback (§5.2 дедуп: был скопирован в restore_frame и on_receive)
    # ------------------------------------------------------------------

    @staticmethod
    def _read_shm_from_actual_name(shm_actual_name: str) -> Optional[Any]:
        """Прочитать кадр напрямую из SharedMemory по фактическому имени (cross-process).

        shm_actual_name приходит от owner через IPC (на Windows включает PID).
        Возвращает ndarray (копию) или None, если изображений нет. Бросает при
        ошибке открытия/распаковки — вызывающий ловит и логирует в своём стиле.
        """
        from multiprocessing import shared_memory as _shm_mod
        import struct as _struct
        import numpy as _np

        shm = _shm_mod.SharedMemory(name=shm_actual_name, create=False)
        try:
            buf = shm.buf
            # Заголовок: num_images (uint32)
            num_images = _struct.unpack("I", buf[0:4])[0]
            if num_images > 0:
                # Заголовок изображения: h, w, c (3x uint32) + dtype char (1 byte)
                h, w, c = _struct.unpack("III", buf[4:16])
                dtype_char = chr(buf[16])
                dtype = _np.dtype(dtype_char)
                offset = 17
                pixel_count = h * w * c
                arr = _np.frombuffer(buf, dtype=dtype, count=pixel_count, offset=offset)
                frame = arr.reshape((h, w, c)).copy()
                del arr, buf  # Освободить ссылки на SHM до close()
                return frame
            return None
        finally:
            shm.close()

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

        # Попытка 1: через MemoryManager (работает в пределах одного процесса)
        try:
            images = self._mm.read_images(shm_owner, shm_name, shm_index, n=1)
            if images:
                msg["frame"] = images[0]
                return msg
        except Exception:
            pass

        # Попытка 2: прямое открытие SharedMemory по shm_actual_name (cross-process)
        shm_actual_name = data.get("shm_actual_name")
        if shm_actual_name:
            try:
                frame = self._read_shm_from_actual_name(shm_actual_name)
                if frame is not None:
                    msg["frame"] = frame
                    return msg
            except Exception as e:
                self._log_error(f"FrameShmMiddleware(generic): SHM fallback failed: {e} (shm={shm_actual_name})")

        # Обе попытки не сработали
        msg["frame"] = None
        self._log_error(
            f"FrameShmMiddleware(generic): frame не восстановлен "
            f"({shm_owner}/{shm_name}[{shm_index}], "
            f"actual={data.get('shm_actual_name', 'N/A')})"
        )
        return msg

    def strip_and_write(self, item: dict) -> dict:
        """Записать frame в SHM, убрать из item, добавить shm_ref.

        Lazy allocation: SHM создаётся при первом кадре (не нужна предварительная
        конфигурация формы кадра).

        Fallback: если SHM write не удался (другая форма кадра, нет памяти), frame
        остаётся в item и пойдёт через pickle в IPC.

        Fan-out (F1, ревью 2026-07-13): producer переиспользует ОДИН item-dict для
        нескольких targets — первый вызов стрипает frame (пиксели → SHM), второй и
        далее видят уже стрипнутый item (frame=None, shm_name уже проставлен). Это
        ВСЁ РАВНО реальный отдельный IPC-send (другому target) — агрегатный
        счётчик границ считает его, per-item поле ``frame_hops`` НЕ задваивает
        (общий mutable item — граница «вдоль линейной цепочки», при fan-out это
        документированное приближение, см. класс-докстринг ``frame_boundary_crossings``).

        Returns:
            item без "frame" (+ shm_ref) или item с "frame" (fallback).
        """
        frame = item.get("frame")
        if frame is None:
            if item.get("shm_name"):
                # Fan-out replay — тот же item уже стрипнут для другого target.
                self._bump_boundary_only()
            return item

        # Lazy allocation при первом кадре + ПЕРЕАЛЛОКАЦИЯ при росте кадра (resize).
        # Блок выделяется под форму первого кадра; если позже кадр становится больше
        # (увеличили ROI / сменили разрешение) — пересоздаём блок под новый размер и
        # переключаем ссылку (новый shm_actual_name едет в каждом сообщении, читатели
        # следуют за ним). Иначе крупный кадр не влезал бы и шёл через медленный pickle.
        if not self._allocated or not self._frame_fits(frame):
            self._allocate_shm(frame)

        try:
            # Round-robin запись по слотам
            idx = self._write_index % self._coll
            self._write_index += 1

            shm_name = self._mm.write_images(self._owner, self._slot, [frame], idx)
            if shm_name:
                # SHM write OK — убрать frame, добавить координаты
                item.pop("frame", None)
                item["owner"] = self._owner
                item["shm_owner"] = self._owner
                item["shm_name"] = self._slot
                item["shm_index"] = idx
                item["shm_actual_name"] = shm_name
            else:
                # SHM write не удался — frame остаётся в item (pickle fallback)
                pass
        except Exception:
            # frame остаётся в item (pickle fallback)
            pass

        # Ф7 G.6: item реально уходит через IPC в другой процесс (SHM-успех ИЛИ
        # pickle-fallback — оба пути кладут item на исходящий транспорт). Dict at
        # Boundary — поле переживает round-trip само по себе, без новых объектов
        # на per-frame пути (правило G.9).
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
            self._alloc_shape = target
            self._alloc_dtype = dtype
            self._write_index = 0  # свежие слоты — пишем с начала кольца
        except Exception as e:
            self._log_error(f"FrameShmMiddleware: allocate SHM error: {e}")

    def strip_data_frame_on_send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
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
        первый это стрип (пишет в SHM) или fan-out-повтор (только считает границу,
        см. его докстринг); граница/кадр НЕ теряется на втором и далее target.
        """
        if msg.get("type") != "data":
            return msg
        data = msg.get("data")
        if isinstance(data, dict):
            self.strip_and_write(data)
        return msg

    # ------------------------------------------------------------------
    # RouterManager middleware-протокол: on_send / on_receive
    # ------------------------------------------------------------------

    def on_send(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить исходящее сообщение: записать frame в SHM, заменить на координаты.

        Если в msg нет ключа "frame" — либо это вообще не кадровое сообщение (нет
        "data" или в нём нет shm-маркера — не трогаем, ноль накладных), либо frame
        уже стрипнут раньше для другого send этого же msg (fan-out replay, F1
        ревью 2026-07-13: считаем границу ЕЩЁ РАЗ — это реальный отдельный IPC-send).
        """
        frame = msg.get("frame")
        if frame is None:
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

        if not self._mm:
            return msg

        # Найти свободный индекс и записать кадр
        free_idx = self._mm.find_free_index(self._owner, self._slot)
        if free_idx is None:
            free_idx = 0

        shm_actual_name = self._mm.write_images(self._owner, self._slot, [frame], free_idx)

        if shm_actual_name is None:
            # Запись не удалась — пропускаем без изменений
            return msg

        # Убрать frame из сообщения (не передавать numpy через IPC)
        msg.pop("frame", None)

        # Добавить SHM-координаты в data (тот же локал — F6b, без повторного setdefault)
        data["shm_name"] = self._slot
        data["shm_index"] = free_idx
        data["shm_actual_name"] = shm_actual_name
        # Сохранить размеры кадра для fallback-чтения
        data["width"] = frame.shape[1]
        data["height"] = frame.shape[0]

        return msg

    def on_receive(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить входящее сообщение: прочитать frame из SHM по координатам.

        Если msg["data"] не содержит SHM-координат — пропускает без изменений.

        Стратегия чтения (приоритет):
          1. MemoryManager.read_images() с координатами из сообщения
          2. Прямое открытие SharedMemory по shm_actual_name (другой OS-процесс)
        """
        data = msg.get("data")
        if not isinstance(data, dict):
            return msg

        shm_name = data.get("shm_name")
        shm_index = data.get("shm_index")

        if shm_name is None or shm_index is None:
            return msg

        # [TRACE] Счётчик для периодического лога
        if not hasattr(self, "_trace_on_recv_cnt"):
            self._trace_on_recv_cnt = 0
        self._trace_on_recv_cnt += 1
        do_trace = self._trace_on_recv_cnt % 30 == 1

        # Координаты из сообщения (приоритет) или конфигурация middleware (fallback)
        owner = data.get("shm_owner", self._owner)
        slot = shm_name or self._slot

        if do_trace:
            logging.getLogger("FrameShmMiddleware").info(
                f"[TRACE] on_receive #{self._trace_on_recv_cnt}: "
                f"owner={owner}, slot={slot}, index={shm_index}, "
                f"shm_actual={data.get('shm_actual_name', 'N/A')}, "
                f"self._owner={self._owner}, self._slot={self._slot}"
            )

        # Попытка 1: через MemoryManager (работает если handles открыты в этом процессе)
        if self._mm:
            images = self._mm.read_images(owner, slot, shm_index, n=1)
            if images:
                msg["frame"] = images[0]
                if do_trace:
                    logging.getLogger("FrameShmMiddleware").info(
                        f"[TRACE] on_receive: MemoryManager SUCCESS, frame shape={images[0].shape}"
                    )
                return msg
            elif do_trace:
                logging.getLogger("FrameShmMiddleware").info(
                    "[TRACE] on_receive: MemoryManager returned empty, trying fallback"
                )

        # Попытка 2: прямое открытие SharedMemory по фактическому имени.
        shm_actual_name = data.get("shm_actual_name")
        if shm_actual_name:
            try:
                frame = self._read_shm_from_actual_name(shm_actual_name)
                if frame is not None:
                    msg["frame"] = frame
                    if do_trace:
                        logging.getLogger("FrameShmMiddleware").info(
                            f"[TRACE] on_receive: SHM fallback SUCCESS, frame shape={frame.shape}"
                        )
            except Exception as exc:
                logging.getLogger("FrameShmMiddleware").warning(
                    "SHM fallback read failed: %s (shm=%s)", exc, shm_actual_name
                )
        elif do_trace:
            logging.getLogger("FrameShmMiddleware").warning(
                "[TRACE] on_receive: no shm_actual_name in data, cannot fallback!"
            )

        if do_trace and "frame" not in msg:
            logging.getLogger("FrameShmMiddleware").warning(
                f"[TRACE] on_receive: FRAME NOT RESTORED! keys={list(data.keys())}"
            )

        return msg
