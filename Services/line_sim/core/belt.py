"""Геометрия ленты: смещение объекта вдоль ленты по энкодеру.

Тот же инвариант трекинга, что у прошивки (Lua) и `SimJournal`:
`trav = (enc_now - job_enc) * FACTOR_MM`. Константы реэкспортируются из
`Services.robot_comm.core.registers` — числа не копируются.
"""

from __future__ import annotations

from Services.robot_comm.core.registers import BELT_UX, BELT_UY, FACTOR_MM

__all__ = ["BELT_UX", "BELT_UY", "FACTOR_MM", "encoder_to_offset_mm"]


def encoder_to_offset_mm(enc_now: float, spawn_enc: float) -> float:
    """Путь объекта вдоль ленты (мм) от энкодера спавна до текущего.

    Post: `encoder_to_offset_mm(e, e) == 0.0`; линейна по `enc_now` с шагом `FACTOR_MM`.
    Направление хода в системе робота — единичный вектор (`BELT_UX`, `BELT_UY`).
    """
    return (enc_now - spawn_enc) * FACTOR_MM
