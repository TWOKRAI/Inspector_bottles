"""Типы данных vfd_comm."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from Services.vfd_comm.core.registers import STATE_FAULT, STATE_REV


@dataclass(slots=True, frozen=True)
class VFDStatus:
    """Статус ПЧ.

    Через мост робота поля heartbeat/comm_errors — телеметрия САМОГО моста
    (Lua-ретранслятора); при прямом RTU-подключении их нет (None).

    ВАЖНО (мост): зеркало обновляется только при обработке VFD_FLAG — без
    регулярного пульса (VfdClient.poll) значения заморожены, а heartbeat не
    растёт даже при живом мосте.
    """

    running: bool
    out_freq_hz: float
    current_a: float
    dcbus_v: float
    fault: int
    status_word: int
    heartbeat: int | None = None  # только мост
    comm_errors: int | None = None  # только мост

    @property
    def reverse(self) -> bool:
        """Крутится ли в реверсе."""
        return self.status_word == STATE_REV

    @property
    def has_fault(self) -> bool:
        """Есть ли авария."""
        return self.fault != 0 or self.status_word == STATE_FAULT

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)
