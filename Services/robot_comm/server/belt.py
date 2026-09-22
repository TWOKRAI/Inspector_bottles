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
import math
import threading

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
        """Pre: см. докстринг класса. Post: ``mm_s == 0.0`` — обычный конструктор
        не подразумевает движения, пока не пришла команда (:meth:`command`);
        для готовой движущейся ленты см. :meth:`from_enc_rate`."""
        self._mm_s_at_max_freq = mm_s_at_max_freq
        self._freq_max_hz = freq_max_hz
        self._mm_s = 0.0
        self._remainder = 0.0
        # "Сырой" режим from_enc_rate: пока не None — advance() считает по
        # enc_rate/tick_s (не по mm_s/FACTOR_MM), но ТЕМ ЖЕ remainder-
        # аккумулятором, что и обычный режим — dt_s == tick_s даёт ровно
        # enc_rate бит-в-бит (см. from_enc_rate, ревью Task 2.1b: раньше было
        # безусловное `return self._raw_rate`, глухое к dt_s — быстрый
        # реальный тик "недодавал" отсчётов). Первая же command() необратимо
        # выключает режим. `mm_s` в этом режиме — НЕ 0 (see from_enc_rate) —
        # раздельные вещи: что возвращает advance() и что показывает mm_s.
        self._raw_rate: int | None = None
        self._raw_tick_s: float = 1.0
        # Task 2.3a: замок берут ТОЛЬКО command() и set_calibration() — обе
        # мутируют несколько атрибутов зараз (_last/_mm_s_at_max_freq/_mm_s/
        # _raw_rate). advance() (горячий путь тикера) замок НЕ берёт — только
        # читает по одному атрибуту, см. докстринг класса.
        self._lock = threading.Lock()
        # Последняя применённая команда ПЧ (run, freq_hz_clamped, reverse) —
        # нужна set_calibration() для пересчёта текущей скорости на новую
        # калибровку без повторного прихода команды.
        self._last: tuple[bool, float, bool] = (False, 0.0, False)

    @classmethod
    def from_enc_rate(cls, enc_rate: int, tick_s: float) -> "BeltDrive":
        """Лента с постоянной скоростью, эквивалентной старому параметру ``enc_rate``.

        Pre: ``tick_s > 0``.
        Post: до первой :meth:`command` :meth:`advance(dt_s)` считает
        ``enc_rate * dt_s / tick_s`` через remainder-аккумулятор (Task 2.1b,
        ревью: раньше `advance` игнорировал `dt_s` и всегда возвращал
        `enc_rate` побитово — с измеренным dt тикера это врало на дельте
        между `dt_s` и `tick_s`, см. `_ticker`). При ``dt_s == tick_s`` — тот
        же бит-точный `enc_rate` на любом числе тиков, что и раньше (старое
        поведение ``RobotSimCore._enc_rate`` — целочисленное приращение, без
        float-дрейфа: та же формула через общую mm_s/FACTOR_MM при
        ``enc_rate=7``, ``tick_s=0.01`` даёт `6999` вместо `7000` за 1000
        тиков — округление на границах, проверено численно; здесь дрейфа нет,
        т.к. `dt_s/tick_s == 1.0` точно в IEEE754 при равных операндах).
        :attr:`mm_s` выставляется сразу (``mm_s_at_max_freq`` — скорость,
        эквивалентная ``enc_rate`` на этом ``tick_s``), чтобы наблюдатели
        (например, паблишер Task 2.2) видели реальную скорость ленты и до
        первой команды ПЧ. После первой команды ПЧ лента переходит в обычный
        режим (и `advance`, и пересчёт `mm_s` — через `command()`).
        """
        mm_s_at_max_freq = enc_rate * FACTOR_MM / tick_s if tick_s > 0 else 0.0
        belt = cls(mm_s_at_max_freq=mm_s_at_max_freq, freq_max_hz=50.0)
        belt._raw_rate = enc_rate
        belt._raw_tick_s = tick_s
        belt._mm_s = mm_s_at_max_freq  # см. докстринг выше — только advance() в "сыром" режиме
        return belt

    def command(self, run: bool, freq_hz: float, reverse: bool = False) -> None:
        """Применить команду ПЧ (пульс VFD_FLAG).

        Pre: ``freq_hz`` — сырое значение в Гц (уже переведённое из RAW*scale
        вызывающей стороной, см. `RobotSimCore._handle_vfd`).
        Post: ``freq_hz`` клэмпится в ``[0, freq_max_hz]``; ``run=False`` ->
        скорость 0 независимо от ``freq_hz``; ``freq_max_hz <= 0`` -> скорость
        0 + WARNING в лог, БЕЗ исключения (деление на ноль). Необратимо
        выключает "сырой" режим :meth:`from_enc_rate`. Запоминает команду в
        ``self._last`` (Task 2.3a) — читает :meth:`set_calibration` при
        рекалибровке на ходу. Под ``self._lock`` — тот же, что берёт
        :meth:`set_calibration`; порядок присваиваний внутри секции: сначала
        ``_mm_s``, потом ``_raw_rate = None`` — :meth:`advance` без замка
        читает эту пару атрибутов, и в другом порядке был бы виден
        полу-переключённый (уже не "сырой", но со старой скоростью) такт.
        """
        with self._lock:
            if self._freq_max_hz <= 0:
                _logger.warning(
                    "BeltDrive.command: freq_max_hz=%.3f <= 0 — скорость принудительно 0",
                    self._freq_max_hz,
                )
                self._mm_s = 0.0
                self._last = (run, 0.0, reverse)
                self._raw_rate = None
                return
            clamped = max(0.0, min(freq_hz, self._freq_max_hz))
            mm_s = (clamped / self._freq_max_hz) * self._mm_s_at_max_freq if run else 0.0
            self._mm_s = -mm_s if reverse else mm_s
            self._last = (run, clamped, reverse)
            self._raw_rate = None

    def advance(self, dt_s: float) -> int:
        """Приращение энкодера (отсчётов) за ``dt_s``.

        Post: дробный остаток копится между вызовами в одном и том же
        аккумуляторе и не теряется — см. докстринг класса. "Сырой" режим
        (:meth:`from_enc_rate`) копит ``enc_rate * dt_s / tick_s``, обычный —
        ``мм_s * dt_s / FACTOR_MM`` (Task 2.1b: раньше "сырой" режим был
        глух к ``dt_s`` — см. :meth:`from_enc_rate`).
        """
        if self._raw_rate is not None:
            self._remainder += self._raw_rate * dt_s / self._raw_tick_s
        else:
            self._remainder += self._mm_s * dt_s / FACTOR_MM
        whole = int(self._remainder)
        self._remainder -= whole
        return whole

    def set_calibration(self, mm_s_at_max_freq: float) -> None:
        """Рекалибровать «мм/с на максимальной частоте» на ходу (Task 2.3a,
        команда ``belt.calibrate``).

        Pre: ``mm_s_at_max_freq`` конечен и ``>= 0`` — иначе ``ValueError``,
        калибровка и скорость НЕ меняются (проверка до захвата замка).
        Post: под ``self._lock`` (тот же, что берёт :meth:`command`) —
        новая калибровка сохраняется; если лента в "сыром" режиме
        (:meth:`from_enc_rate`, ``_raw_rate is not None``) — режим
        выключается, как если бы пришла команда ``run=True`` на
        ``freq_max_hz`` (лента едет дальше, на новой скорости, а не
        останавливается); иначе скорость пересчитывается из последней
        применённой команды (``self._last``). Порядок присваиваний —
        сначала ``_mm_s``, потом ``_raw_rate = None`` — см. докстринг
        :meth:`command`.
        """
        if not math.isfinite(mm_s_at_max_freq) or mm_s_at_max_freq < 0:
            raise ValueError(f"mm_s_at_max_freq должен быть конечным и >= 0, получено {mm_s_at_max_freq!r}")
        with self._lock:
            self._mm_s_at_max_freq = mm_s_at_max_freq
            if self._raw_rate is not None:
                self._mm_s = mm_s_at_max_freq
                self._raw_rate = None
                self._last = (True, self._freq_max_hz, False)
            else:
                run, freq_hz, reverse = self._last
                mm_s = (freq_hz / self._freq_max_hz) * mm_s_at_max_freq if run and self._freq_max_hz > 0 else 0.0
                self._mm_s = -mm_s if reverse else mm_s

    @property
    def mm_s(self) -> float:
        """Текущая скорость ленты, мм/с (отрицательна при ``reverse=True``)."""
        return self._mm_s

    @property
    def mm_s_at_max_freq(self) -> float:
        """Текущая калибровка «мм/с на максимальной частоте» (Task 2.3a)."""
        return self._mm_s_at_max_freq

    @property
    def freq_max_hz(self) -> float:
        """Максимальная частота ПЧ, Гц — верхняя граница валидации команд."""
        return self._freq_max_hz

    @property
    def state(self) -> dict:
        """Эффективное состояние ленты: ``{run, freq_hz, reverse}`` — команда
        ПЧ, что бы ни писало mailbox последним (Task 2.3a, ``belt.status``).

        В "сыром" режиме (:meth:`from_enc_rate`, ни одной :meth:`command`/
        :meth:`set_calibration` ещё не было) — как если бы пришла команда
        ``run=True`` на ``freq_max_hz``. Читается под ``self._lock`` —
        ``_raw_rate`` и ``_last`` должны наблюдаться согласованной парой.
        """
        with self._lock:
            if self._raw_rate is not None:
                return {"run": True, "freq_hz": self._freq_max_hz, "reverse": False}
            run, freq_hz, reverse = self._last
        return {"run": run, "freq_hz": freq_hz, "reverse": reverse}
