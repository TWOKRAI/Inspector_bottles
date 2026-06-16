"""WordAssembler — потоковый жадный матчер дисков под слоты слова.

Конвейер-сортировщик: диски едут по одному, нейросеть распознаёт букву+угол. Каждый
диск предлагается матчеру (``offer``); он кладётся в ПЕРВЫЙ незаполненный слот с этой
буквой и возвращает задание роботу {x_mm, y_mm, angle_deg}. Ненужные буквы и дубли
(когда все такие слоты уже заполнены) отклоняются (``None``). Слово готово (``done``),
когда заполнены все слоты.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import geometry
from .geometry import Point


@dataclass
class Slot:
    """Один слот слова: целевая буква и координата центра диска на столе (мм)."""

    char: str
    x_mm: float
    y_mm: float
    filled: bool = False


class WordAssembler:
    """Состояние раскладки одного слова (какие слоты уже заполнены)."""

    def __init__(self, slots: list[Slot]) -> None:
        self._slots: list[Slot] = list(slots)

    @classmethod
    def from_word(
        cls,
        text: str,
        first: Point,
        last: Point,
        gap_slots: int = 1,
    ) -> WordAssembler:
        """Собрать матчер из слова и координат первого/последнего диска."""
        cells = geometry.parse_word(text, gap_slots)
        letters = [c for c in cells if c is not None]
        positions = geometry.slot_positions(first, last, cells)
        slots = [Slot(ch, x, y) for ch, (x, y) in zip(letters, positions)]
        return cls(slots)

    # --- состояние ---

    @property
    def slots(self) -> list[Slot]:
        """Слоты слова (для отрисовки/прогресса)."""
        return self._slots

    @property
    def total(self) -> int:
        """Сколько всего слотов (букв)."""
        return len(self._slots)

    @property
    def filled_count(self) -> int:
        """Сколько слотов заполнено."""
        return sum(1 for s in self._slots if s.filled)

    @property
    def remaining(self) -> int:
        """Сколько слотов осталось заполнить."""
        return self.total - self.filled_count

    @property
    def done(self) -> bool:
        """Все слоты заполнены (и слово непустое)."""
        return bool(self._slots) and all(s.filled for s in self._slots)

    @property
    def next_letter(self) -> str:
        """Первая ещё не заполненная буква (или '')."""
        for s in self._slots:
            if not s.filled:
                return s.char
        return ""

    def reset(self) -> None:
        """Снять все заполнения (начать раскладку заново)."""
        for s in self._slots:
            s.filled = False

    # --- матчинг ---

    def offer(
        self,
        label: str,
        angle_deg: float,
        angle_valid: bool,
        *,
        zero_deg: float = 0.0,
        sign: float = 1.0,
    ) -> dict | None:
        """Предложить распознанный диск. Вернёт задание роботу или None (не нужен).

        Жадно: первый незаполненный слот с буквой ``label``. ``zero_deg``/``sign`` —
        калибровка угла (см. geometry.correction_angle).
        """
        norm = (label or "").strip().upper()
        if not norm:
            return None
        for idx, s in enumerate(self._slots):
            if not s.filled and s.char == norm:
                s.filled = True
                corr = geometry.correction_angle(angle_deg, angle_valid, zero_deg, sign)
                return {
                    "slot": idx,
                    "char": norm,
                    "x_mm": s.x_mm,
                    "y_mm": s.y_mm,
                    "angle_deg": corr,
                    "raw_angle_deg": float(angle_deg),
                }
        return None
