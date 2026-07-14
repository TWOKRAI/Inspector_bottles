# -*- coding: utf-8 -*-
"""ProcessIO — facade для исходящих взаимодействий процесса.

Используется в адаптерах сервисов (Ports & Adapters паттерн) чтобы избежать
дублирования boilerplate: Message factory + transport + SHM helpers + logs.

НЕ используется самим ProcessModule — это отдельный composition-helper
поверх существующих механизмов (MessageAdapter, send_message, memory_manager).

Пример использования в адаптере прототипа:

    class _CameraAdapter:
        def __init__(self, process):
            self._io = ProcessIO(process)

        def send_frame_to_processor(self, data: dict) -> None:
            self._io.send_data("processor", "frame_ready", data)

        def write_frame_to_shm(self, frame) -> dict | None:
            return self._io.write_frames_to_shm("camera", "camera_frame", [frame])
"""

from __future__ import annotations

from typing import Optional

from ...message_module import MessageAdapter
from ..interfaces import IProcessModule


class ProcessIO:
    """IO-facade для ProcessModule.

    Инкапсулирует типовые паттерны взаимодействия процесса с инфраструктурой:
    - IPC: создание Message + отправка через send_message в одном вызове
    - SHM: запись кадров с автоматическим подбором свободного индекса
    - Logs: делегация в логгер процесса

    Attrs:
        _p: Ссылка на ProcessModule (или любую реализацию IProcessModule).
        _msg: MessageAdapter с sender=process.name.
    """

    def __init__(self, process: IProcessModule) -> None:
        self._p = process
        self._msg = MessageAdapter(sender=process.name)
        # H7 (Ф7 G.3): round-robin индекс записи per (region, slot) — тот же контракт,
        # что в FrameShmMiddleware (снят сломанный find_free_index, всегда 0).
        self._shm_write_index: dict[tuple, int] = {}

    # ---- IPC: исходящие сообщения ----

    def send_data(self, target: str, data_type: str, data: dict) -> bool:
        """Отправить DATA-сообщение целевому процессу."""
        msg = self._msg.data(targets=[target], data_type=data_type, data=data)
        return self._p.send_message(target, msg.to_dict())

    def send_command(
        self,
        target: str,
        command: str,
        args: dict,
        data: Optional[dict] = None,
    ) -> bool:
        """Отправить COMMAND-сообщение целевому процессу.

        Единый конверт (Ф7 G.2, F6): приоритет payload (data > args) — в
        MessageAdapter.command; здесь прокидываем оба параметра.
        """
        msg = self._msg.command(targets=[target], command=command, args=args, data=data)
        return self._p.send_message(target, msg.to_dict())

    def send_event(self, target: str, event_type: str, event_data: dict) -> bool:
        """Отправить EVENT-сообщение целевому процессу."""
        msg = self._msg.event(event_type=event_type, targets=[target], event_data=event_data)
        return self._p.send_message(target, msg.to_dict())

    # ---- SHM: запись кадров ----

    def write_frames_to_shm(
        self,
        region: str,
        slot: str,
        frames: list,
    ) -> Optional[dict]:
        """Записать кадры в SHM-слот (round-robin по слотам, тот же контракт, что
        FrameShmMiddleware — H7, Ф7 G.3).

        Returns:
            dict {"shm_name", "shm_index", "shm_actual_name", "shm_seqlock"} при
            успехе; None если memory_manager недоступен, слот не создан или запись
            не удалась. ``shm_seqlock`` — АВТОРИТЕТНО из get_memory_data (иначе
            cross-process reader читал бы не с того offset).
        """
        mm = getattr(self._p, "memory_manager", None)
        if not mm:
            return None
        md = mm.get_memory_data(region, slot)
        if not md:
            return None
        coll = md.get("coll", {}).get(slot, 1) or 1
        key = (region, slot)
        idx = self._shm_write_index.get(key, 0) % coll
        self._shm_write_index[key] = idx + 1
        actual = mm.write_images(region, slot, frames, idx)
        if not actual:
            return None
        return {
            "shm_name": slot,
            "shm_index": idx,
            "shm_actual_name": actual,
            "shm_seqlock": bool(md.get("seqlock", False)),  # H7: контракт как в middleware
        }

    # ---- Logs ----

    def log_info(self, text: str) -> None:
        """Делегировать info-лог в процесс."""
        self._p._log_info(text)

    def log_error(self, text: str) -> None:
        """Делегировать error-лог в процесс."""
        self._p._log_error(text)
