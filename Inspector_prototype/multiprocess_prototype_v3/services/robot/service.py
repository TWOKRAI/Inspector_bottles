"""RobotService — бизнес-логика отбраковки."""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype_v3.services.robot.ports import RobotOutputPort


class RobotService:
    """Сервис отбраковки. Чистая логика без привязки к фреймворку."""

    def __init__(self, output: RobotOutputPort, reject_delay: float = 0.5) -> None:
        self._out = output
        self._reject_delay = reject_delay
        self._action_count = 0

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def reject_delay(self) -> float:
        return self._reject_delay

    @reject_delay.setter
    def reject_delay(self, value: float) -> None:
        self._reject_delay = max(0.0, value)

    def process_rejection(self, frame_id: int, defects: list[dict]) -> dict:
        """Обработать отбраковку: залогировать каждый дефект."""
        for defect in defects:
            self._action_count += 1
            center = defect.get("center", [0, 0])
            area = defect.get("area", 0)
            log_text = self.format_log_entry(frame_id, center, area)
            self._out.log_info(f"REJECT #{self._action_count}: frame={frame_id}, pos=({center[0]}, {center[1]}), area={area}")
            self._out.write_log(log_text)
        return {"status": "ok", "action_id": self._action_count}

    def format_log_entry(self, frame_id: int, center: list, area: int) -> str:
        """Форматировать строку лога отбраковки."""
        ts = datetime.datetime.now().isoformat()
        return f"{ts} | frame={frame_id} | x={center[0]} y={center[1]} | area={area}\n"
