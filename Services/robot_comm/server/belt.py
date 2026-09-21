"""Модель ленты конвейера (line-sim, Ф2 «правда ленты», Task 2.1).

Инспектор шлёт команду ПЧ (частота + направление) на мост `vfd_belt →
robot_main` — та же команда, что и на боевом стенде. `BeltDrive` переводит её
в фактическую скорость ленты и отдаёт `RobotSimCore` приращение энкодера за
тик Motion-цикла.

Лента — самостоятельный класс каталога устройств ([`vision.md`](../../../../plans/line-sim/vision.md)
§Каталог), а не формула внутри `_handle_vfd`: когда появится ПЧ без моста
(`Services/vfd_comm/protocols/gd20_direct.yaml`), той же лентой должен уметь
управлять другой хост.

Масштаб «Гц → мм/с» реального стенда в коде не найден (владелец: «точность
мира — примерная, достаточно») — `mm_s_at_max_freq` остаётся калибровочной
ручкой, а не константой.

# ponytail: лежит рядом с единственным потребителем (`sim_core.py`); переезжает
# в Services/line_sim, когда лентой начнёт управлять второй хост (Task 2.2+).
"""

from __future__ import annotations

import logging

from Services.robot_comm.core.registers import FACTOR_MM

_logger = logging.getLogger(__name__)


class BeltDrive:
    """Лента конвейера: команда ПЧ -> мм/с -> отсчёты энкодера за тик.

    Pre: ``mm_s_at_max_freq >= 0``; ``freq_max_hz`` может быть ``<= 0``
    (см. :meth:`command` — скорость принудительно 0, без деления на ноль).
    Post: :meth:`advance` возвращает целое число отсчётов энкодера за
    ``dt_s``; дробный остаток копится во float-аккумуляторе между вызовами —
    средняя скорость точна при любом ``dt_s`` (в т.ч. на низкой частоте, где
    старый `max(1, round(...))` тихо врал о скорости, не давая ленте ехать
    медленнее одного отсчёта за тик).

    Скорость меняется только по вызову :meth:`command` — это отражает
    ограничение прошивки (зеркало ПЧ обновляется только по пульсу VFD_FLAG,
    см. `RobotSimCore._handle_vfd`), не разгон/торможение по рампе (вне
    области этой задачи).
    """

    def __init__(self, mm_s_at_max_freq: float = 100.0, freq_max_hz: float = 50.0) -> None:
        self._mm_s_at_max_freq = mm_s_at_max_freq
        self._freq_max_hz = freq_max_hz
        self._mm_s = 0.0
        self._remainder = 0.0
        # "Сырой" режим from_enc_rate: пока не None — advance() возвращает
        # это целое число побитово, БЕЗ remainder-арифметики (float-округление
        # не гарантирует бит-точность на N тиков, см. from_enc_rate). Первая
        # же command() необратимо выключает режим.
        self._raw_rate: int | None = None

    @classmethod
    def from_enc_rate(cls, enc_rate: int, tick_s: float) -> "BeltDrive":
        """Лента с постоянной скоростью, эквивалентной старому параметру ``enc_rate``.

        Pre: ``tick_s > 0``.
        Post: до первой :meth:`command` :meth:`advance` возвращает ``enc_rate``
        побитово на любом числе тиков (старое поведение
        ``RobotSimCore._enc_rate`` — целочисленное приращение, без float —
        воспроизводится точно, а не приближённо через общую формулу
        mm_s/FACTOR_MM, которая на границах округления даёт дрейф ±1 на 1000
        тиках). После первой команды ПЧ лента переходит в обычный режим.
        """
        mm_s_at_max_freq = enc_rate * FACTOR_MM / tick_s if tick_s > 0 else 0.0
        belt = cls(mm_s_at_max_freq=mm_s_at_max_freq, freq_max_hz=50.0)
        belt._raw_rate = enc_rate
        return belt

    def command(self, run: bool, freq_hz: float, reverse: bool = False) -> None:
        """Применить команду ПЧ (пульс VFD_FLAG).

        Pre: ``freq_hz`` — сырое значение в Гц (уже переведённое из RAW*scale
        вызывающей стороной, см. `RobotSimCore._handle_vfd`).
        Post: ``freq_hz`` клэмпится в ``[0, freq_max_hz]``; ``run=False`` ->
        скорость 0 независимо от ``freq_hz``; ``freq_max_hz <= 0`` -> скорость
        0 + WARNING в лог, БЕЗ исключения (деление на ноль). Необратимо
        выключает "сырой" режим :meth:`from_enc_rate`.
        """
        self._raw_rate = None
        if self._freq_max_hz <= 0:
            _logger.warning(
                "BeltDrive.command: freq_max_hz=%.3f <= 0 — скорость принудительно 0",
                self._freq_max_hz,
            )
            self._mm_s = 0.0
            return
        clamped = max(0.0, min(freq_hz, self._freq_max_hz))
        mm_s = (clamped / self._freq_max_hz) * self._mm_s_at_max_freq if run else 0.0
        self._mm_s = -mm_s if reverse else mm_s

    def advance(self, dt_s: float) -> int:
        """Приращение энкодера (отсчётов) за ``dt_s``.

        Post: дробный остаток ``мм_s * dt_s / FACTOR_MM`` копится между
        вызовами в аккумуляторе и не теряется — см. докстринг класса.
        """
        if self._raw_rate is not None:
            return self._raw_rate
        self._remainder += self._mm_s * dt_s / FACTOR_MM
        whole = int(self._remainder)
        self._remainder -= whole
        return whole

    @property
    def mm_s(self) -> float:
        """Текущая скорость ленты, мм/с (отрицательна при ``reverse=True``)."""
        return self._mm_s
