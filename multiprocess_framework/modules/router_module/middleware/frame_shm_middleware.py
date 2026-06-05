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
            read_images/find_free_index/create_memory_dict).
        owner: имя процесса-владельца SHM-региона (для write).
        slot: имя SHM-слота (для write).
        coll: количество SHM-слотов (размер ring buffer) — generic-путь.
        log_error: callback логирования ошибок — generic-путь.
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
        self._allocated = False
        self._write_index = 0

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

        Returns:
            item без "frame" (+ shm_ref) или item с "frame" (fallback).
        """
        frame = item.get("frame")
        if frame is None:
            return item

        # Lazy allocation при первом кадре
        if not self._allocated:
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

        return item

    def _allocate_shm(self, frame: Any) -> None:
        """Выделить SHM-блоки по форме первого кадра."""
        try:
            shape = frame.shape
            dtype = str(frame.dtype)
            memory_names = {
                self._slot: (1, shape, dtype),
            }
            self._mm.create_memory_dict(self._owner, memory_names, self._coll)
            self._allocated = True
        except Exception as e:
            self._log_error(f"FrameShmMiddleware: allocate SHM error: {e}")

    def strip_data_frame_on_send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send-middleware для data-pipeline (P3.1.2): вынести frame из msg["data"] в SHM.

        Регистрируется через ``RouterManager.add_send_middleware`` в GenericProcess —
        Claim Check кадров становится делом хаба, а не явного вызова в
        SourceProducer/PipelineExecutor. Использует generic-семантику
        :meth:`strip_and_write` (lazy-alloc, round-robin ring, pickle-fallback) поверх
        ``msg["data"]`` (item остаётся тем же dict — мутируется на месте).

        Срабатывает ТОЛЬКО на data-кадрах (``type=="data"`` и frame в ``data``) —
        команды/heartbeat/state проходят без изменений (быстрый guard, ноль накладных
        на не-кадровых сообщениях). Путь top-level-frame (`wire.configure` → on_send)
        не затрагивается: там frame в ``msg["frame"]``, а не в ``msg["data"]``.

        Мультикаст: producer переиспользует один item для нескольких targets; первый
        ``router.send`` стрипает его (frame → SHM, координаты в data), последующие
        видят item уже без frame → no-op. Паритет с прежним «strip один раз до цикла».
        """
        if msg.get("type") != "data":
            return msg
        data = msg.get("data")
        if isinstance(data, dict) and data.get("frame") is not None:
            self.strip_and_write(data)
        return msg

    # ------------------------------------------------------------------
    # RouterManager middleware-протокол: on_send / on_receive
    # ------------------------------------------------------------------

    def on_send(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить исходящее сообщение: записать frame в SHM, заменить на координаты.

        Если в msg нет ключа "frame" или frame не numpy ndarray — пропускает без изменений.
        """
        frame = msg.get("frame")
        if frame is None:
            return msg

        # Проверка что это numpy ndarray (без жёсткого импорта numpy на уровне модуля)
        if not hasattr(frame, "shape"):
            return msg

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

        # Добавить SHM-координаты в data
        data = msg.setdefault("data", {})
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
