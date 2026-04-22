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
        """Отправить COMMAND-сообщение целевому процессу."""
        msg = self._msg.command(
            targets=[target], command=command, args=args, data=data or {}
        )
        return self._p.send_message(target, msg.to_dict())

    def send_event(self, target: str, event_type: str, event_data: dict) -> bool:
        """Отправить EVENT-сообщение целевому процессу."""
        msg = self._msg.event(
            event_type=event_type, targets=[target], event_data=event_data
        )
        return self._p.send_message(target, msg.to_dict())

    # ---- SHM: запись кадров ----

    def write_frames_to_shm(
        self,
        region: str,
        slot: str,
        frames: list,
    ) -> Optional[dict]:
        """Записать кадры в SHM-слот с автоматическим подбором индекса.

        Returns:
            dict {"shm_name": slot, "shm_index": idx, "shm_actual_name": actual}
            если запись успешна; None если memory_manager недоступен или
            запись не удалась.
        """
        mm = getattr(self._p, "memory_manager", None)
        if not mm:
            return None
        idx = mm.find_free_index(region, slot)
        if idx is None:
            idx = 0
        actual = mm.write_images(region, slot, frames, idx)
        if not actual:
            return None
        return {
            "shm_name": slot,
            "shm_index": idx,
            "shm_actual_name": actual,
        }

    # ---- Logs ----

    def log_info(self, text: str) -> None:
        """Делегировать info-лог в процесс."""
        self._p._log_info(text)

    def log_error(self, text: str) -> None:
        """Делегировать error-лог в процесс."""
        self._p._log_error(text)
