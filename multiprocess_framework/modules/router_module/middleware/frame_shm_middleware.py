# -*- coding: utf-8 -*-
"""FrameShmMiddleware — middleware для прозрачной передачи кадров через SHM.

Автоматизирует запись/чтение numpy-кадров в shared memory через MemoryManager.
Подключается к RouterManager через add_send_middleware / add_receive_middleware.

Протокол:
  - on_send: если msg содержит ключ "frame" (numpy ndarray), записывает в SHM,
    удаляет "frame" из msg и добавляет SHM-координаты в msg["data"].
  - on_receive: если msg["data"] содержит "shm_name" и "shm_index",
    читает кадр из SHM и кладёт в msg["frame"].
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class FrameShmMiddleware:
    """Middleware для прозрачной сериализации/десериализации кадров через SHM.

    Args:
        memory_manager: экземпляр MemoryManager с API write_images/read_images.
        owner: имя процесса-владельца SHM-региона (например "camera").
        slot: имя SHM-слота (например "camera_frame").
    """

    def __init__(self, memory_manager: Any, owner: str, slot: str) -> None:
        self._mm = memory_manager
        self._owner = owner
        self._slot = slot

    def on_send(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Перехватить исходящее сообщение: записать frame в SHM, заменить на координаты.

        Если в msg нет ключа "frame" или frame не является numpy ndarray —
        пропускает сообщение без изменений.
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

        shm_actual_name = self._mm.write_images(
            self._owner, self._slot, [frame], free_idx
        )

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
          1. MemoryManager.read_images() — если handles уже открыты (owner-процесс)
          2. Прямое открытие SharedMemory по shm_actual_name (consumer-процесс, другой OS-процесс)
             shm_actual_name передаётся от owner через IPC (включает PID на Windows)
        """
        data = msg.get("data")
        if not isinstance(data, dict):
            return msg

        shm_name = data.get("shm_name")
        shm_index = data.get("shm_index")

        if shm_name is None or shm_index is None:
            return msg

        # Попытка 1: через MemoryManager (работает если handles открыты в этом процессе)
        if self._mm:
            images = self._mm.read_images(self._owner, self._slot, shm_index, n=1)
            if images:
                msg["frame"] = images[0]
                return msg

        # Попытка 2: прямое открытие SharedMemory по фактическому имени.
        # TODO: Костыль — дублирует бинарный формат из write_images/create_shm_blocks.
        #   Правильное решение: MemoryManager.attach_remote(shm_actual_name) — подключение
        #   к чужому SHM через штатный API без знания layout.
        #   Рефакторинг: https://github.com/... (Phase 5 или отдельный ADR)
        shm_actual_name = data.get("shm_actual_name")
        if shm_actual_name:
            try:
                from multiprocessing import shared_memory as _shm_mod
                import struct as _struct
                import numpy as _np

                shm = _shm_mod.SharedMemory(name=shm_actual_name, create=False)
                try:
                    buf = shm.buf
                    # Читаем заголовок: num_images (uint32)
                    num_images = _struct.unpack("I", buf[0:4])[0]
                    if num_images > 0:
                        # Заголовок изображения: h, w, c (3x uint32) + dtype char (1 byte)
                        h, w, c = _struct.unpack("III", buf[4:16])
                        dtype_char = chr(buf[16])
                        dtype = _np.dtype(dtype_char)
                        offset = 17
                        pixel_count = h * w * c
                        arr = _np.frombuffer(buf, dtype=dtype, count=pixel_count, offset=offset)
                        msg["frame"] = arr.reshape((h, w, c)).copy()
                finally:
                    shm.close()
            except Exception:
                # Не удалось прочитать — пропускаем без frame
                pass

        return msg
