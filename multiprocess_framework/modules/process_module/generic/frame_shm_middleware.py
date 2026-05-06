"""FrameShmMiddleware — трансформация frame ↔ SHM ref для data pipeline.

Два метода:
- restore_frame(msg) — входящее IPC сообщение → item с frame из SHM
- strip_and_write(item) — item с frame → SHM write + item без frame (с shm_ref)

Плагин работает с item["frame"] как с обычным ndarray — не знает про SHM.
"""

from __future__ import annotations

from typing import Any, Callable


class FrameShmMiddleware:
    """Middleware для frame ↔ SHM на границах GenericProcess.

    Args:
        memory_manager: MemoryManager из shared_resources_module
        owner: имя процесса-владельца SHM (для write)
        slot: имя SHM слота (для write)
        coll: количество SHM-слотов (ring buffer size)
        log_error: callback для логирования ошибок
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

    def restore_frame(self, msg: dict) -> dict:
        """Восстановить frame из SHM ref в item.

        Входящий msg содержит shm_name, shm_index (или owner + slot + index).
        Читает ndarray из SHM → кладёт в msg["frame"].

        Стратегия (как в router FrameShmMiddleware):
          1. MemoryManager.read_images() — если SHM handle есть в этом процессе
          2. Fallback: прямое открытие SharedMemory по shm_actual_name
             (cross-process, другой OS-процесс)
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
                from multiprocessing import shared_memory as _shm_mod
                import struct as _struct
                import numpy as _np

                shm = _shm_mod.SharedMemory(name=shm_actual_name, create=False)
                try:
                    buf = shm.buf
                    num_images = _struct.unpack("I", buf[0:4])[0]
                    if num_images > 0:
                        h, w, c = _struct.unpack("III", buf[4:16])
                        dtype_char = chr(buf[16])
                        dtype = _np.dtype(dtype_char)
                        offset = 17
                        pixel_count = h * w * c
                        arr = _np.frombuffer(
                            buf, dtype=dtype, count=pixel_count, offset=offset,
                        )
                        frame = arr.reshape((h, w, c)).copy()
                        del arr, buf  # Освободить ссылки на SHM до close()
                        msg["frame"] = frame
                        return msg
                finally:
                    shm.close()
            except Exception as e:
                self._log_error(
                    f"FrameShmMiddleware(generic): SHM fallback failed: {e} "
                    f"(shm={shm_actual_name})"
                )

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

        Lazy allocation: SHM создаётся при первом кадре (не нужна
        предварительная конфигурация формы кадра).

        Fallback: если SHM write не удался (другая форма кадра, нет памяти),
        frame остаётся в item и пойдёт через pickle в IPC.

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

            shm_name = self._mm.write_images(
                self._owner, self._slot, [frame], idx
            )
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
