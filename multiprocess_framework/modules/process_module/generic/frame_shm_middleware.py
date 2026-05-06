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
        log_error: callback для логирования ошибок
    """

    def __init__(
        self,
        memory_manager: Any,
        owner: str,
        slot: str = "output_frames",
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._mm = memory_manager
        self._owner = owner
        self._slot = slot
        self._log_error = log_error or (lambda msg: None)

    def restore_frame(self, msg: dict) -> dict:
        """Восстановить frame из SHM ref в item.

        Входящий msg содержит shm_name, shm_index (или owner + slot + index).
        Читает ndarray из SHM → кладёт в msg["frame"].
        """
        data = msg.get("data", msg)

        shm_owner = data.get("owner", data.get("shm_owner", ""))
        shm_name = data.get("shm_name", "")
        shm_index = data.get("shm_index", 0)

        if not shm_owner or not shm_name:
            # Нет SHM ref — возможно frame уже в сообщении или нет frame
            return msg

        try:
            images = self._mm.read_images(shm_owner, shm_name, shm_index, n=1)
            if images:
                msg["frame"] = images[0]
            else:
                msg["frame"] = None
                self._log_error(
                    f"FrameShmMiddleware: read_images вернул пустой результат "
                    f"({shm_owner}/{shm_name}[{shm_index}])"
                )
        except Exception as e:
            msg["frame"] = None
            self._log_error(f"FrameShmMiddleware: restore_frame error: {e}")

        return msg

    def strip_and_write(self, item: dict) -> dict:
        """Записать frame в SHM, убрать из item, добавить shm_ref.

        Returns:
            item без "frame", с добавленными owner/shm_name/shm_index.
            Если frame нет или запись не удалась — item as-is (без frame).
        """
        frame = item.pop("frame", None)
        if frame is None:
            return item

        try:
            free_idx = self._mm.find_free_index(self._owner, self._slot)
            if free_idx is None:
                # Нет свободного слота — перезаписываем 0
                free_idx = 0

            shm_name = self._mm.write_images(
                self._owner, self._slot, [frame], free_idx
            )
            if shm_name:
                item["owner"] = self._owner
                item["shm_name"] = shm_name
                item["shm_index"] = free_idx
            else:
                self._log_error("FrameShmMiddleware: write_images вернул None")
        except Exception as e:
            self._log_error(f"FrameShmMiddleware: strip_and_write error: {e}")

        return item
