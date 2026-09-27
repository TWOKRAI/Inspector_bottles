"""Общие мелочи между read-only видами протокола v2 (``sim_view.py``,
``z_view.py``, T2.V/T2.W).

Выделено отдельным модулем ревью T2.W (находка F6): раньше ``z_view.py``
импортировал ``_REFRESH_MS``/``_decode_reg`` ИЗ ``sim_view.py`` — обратный
импорт ``sim_view -> z_view`` на уровне модуля (нужен, чтобы ``build_window``
не держал локальный импорт) зациклился бы. Оба модуля читают отсюда,
``sim_view.py`` — из ``z_view.py``, цикла больше нет.
"""

from __future__ import annotations

#: период таймера перерисовки, мс (contract T2.V: "~33 мс").
_REFRESH_MS = 33


def _decode_reg(raw: int) -> float:
    """u16-регистр позы (×10, two's complement) -> инженерное значение (мм/°)."""
    signed = raw - 65536 if raw >= 0x8000 else raw
    return signed / 10.0
