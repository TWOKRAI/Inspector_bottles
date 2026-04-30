"""Команды для RobotProcess.

Фабричные функции получают зависимости как аргументы и возвращают dict.
"""
from __future__ import annotations

import time


def build_command_table(service) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        service: RobotService instance.
    """

    def cmd_reject(data: dict) -> dict:
        """Команда отбраковки — делегация в сервис."""
        result = service.process_rejection(
            frame_id=data.get("frame_id", 0),
            defects=data.get("defects", []),
        )
        if service.reject_delay > 0:
            time.sleep(service.reject_delay)
        return result

    return {
        "reject_item": cmd_reject,
    }
