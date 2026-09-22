"""Журнал обмена симулятора: что ПРИНЯЛ от ПК ↔ что ОТДАЛ робот.

Зачем: увидеть глазами, сколько заданий инспектор шлёт на ОДНУ физическую деталь.
Классический дефект тракта — задание на каждый кадр с детекцией: очередь драйвера
(`Services/device_hub/drivers/robot_driver.py`) — обычная FIFO без дедупа, поэтому
три кадра = три подхода робота подряд, каждый со сдвигом на полный цикл предыдущего
(«робот видит три объекта, да ещё и с задержкой»).

Две стороны журнала:

* ``in``  — записи Modbus, пришедшие от ПК (хук ``action=`` сервера pymodbus);
            чтения не логируются (их сотни в секунду), но считаются.
* ``out`` — события ядра симулятора (``RobotSimCore.on_event``): приём задания,
            завершение, стоп, серво — зеркало ``print()`` прошивки.

ДЕТЕКТОР ДУБЛЕЙ. Наивное «те же X/Y» не годится: лента едет, и та же деталь на
следующем кадре снята уже в другой точке. Инвариант трекинга (из Lua
``cvt_universal_full.lua``: ``trav = (enc_now - job_enc) * FACTOR_MM``,
``px = job_x + UX*trav``, ``py = job_y + UY*trav``) даёт правильную проверку:
два задания указывают на ОДНУ деталь, если разница координат объясняется
проездом ленты за разницу энкодеров::

    невязка = |(Δx, Δy) - (UX, UY) * Δenc * FACTOR_MM|   < dup_radius_mm

При равных энкодерах это вырождается в обычное расстояние между точками.

Потокобезопасно: ``on_write`` зовётся из потока сервера, ``on_event`` — из
ticker-потока, ``drain`` — из потока GUI.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from Services.modbus import Reg, RegBlock, RegDW
from Services.modbus.sdk.datatypes import decode_int16, decode_int32

# Геометрия трекинга (FACTOR_MM, BELT_UX/UY) — константы прошивки, живут в карте
# протокола: детектор дублей обязан считать ровно ту же арифметику, что и робот.
from Services.robot_comm.core.registers import (
    BELT_UX,
    BELT_UY,
    FACTOR_MM,
    REG_JOB_ECAP,
    REG_JOB_FLAG,
    REG_JOB_X,
    REG_JOB_Y,
    XY_SCALE,
    build_register_map,
)

#: Функциональные коды Modbus, означающие ЗАПИСЬ (для подписи строки журнала).
_FC_NAMES = {5: "W1", 6: "W", 15: "W*", 16: "W*"}


@dataclass(frozen=True)
class JournalEntry:
    """Одна строка журнала.

    Attributes:
        t:    Момент по монотонным часам, сек.
        side: ``"in"`` (ПК → робот) или ``"out"`` (робот → ПК).
        text: Готовая строка для показа.
        tag:  Класс события: ``""`` | ``"job"`` | ``"dup"`` | ``"flag"`` | ``"done"``.
    """

    t: float
    side: str
    text: str
    tag: str = ""


@dataclass(frozen=True)
class JobRecord:
    """Задание, увиденное журналом в момент взвода ``job_flag=1``."""

    t: float
    x_mm: float
    y_mm: float
    ecap: int
    index: int


def _build_decode_table(word_order: str = "little") -> dict[int, tuple[str, float, bool]]:
    """Обратная карта адрес → (имя, шкала, знаковость) из RegisterMap.

    Единственный источник истины протокола — ``build_register_map``; здесь только
    разворот в адресный вид, чтобы подписывать сырые записи с провода.
    """
    table: dict[int, tuple[str, float, bool]] = {}
    rmap = build_register_map(word_order)
    for name in rmap.names():
        entry = rmap.entry(name)
        if isinstance(entry, RegDW):
            # Пара слов: младшее подписываем именем, старшее — служебно (значение
            # DW собирается отдельно, см. _decode_dw).
            table[entry.address] = (name, entry.scale, entry.signed)
            table[entry.address + 1] = (f"{name}^", 1.0, False)
        elif isinstance(entry, RegBlock):
            if entry.fields:
                for i, fld in enumerate(entry.fields):
                    table[entry.address + i] = (f"{name}.{fld.name}", fld.scale, fld.signed)
            else:
                for i in range(entry.count):
                    table[entry.address + i] = (f"{name}[{i}]", 1.0, False)
        elif isinstance(entry, Reg):
            table[entry.address] = (name, entry.scale, entry.signed)
    return table


def _format_value(raw: int, scale: float, signed: bool) -> str:
    """Сырое слово → человеческое значение по шкале карты."""
    value = decode_int16(raw) if signed else raw
    if scale != 1.0:
        return f"{value / scale:.1f}"
    return str(value)


class SimJournal:
    """Кольцевой журнал обмена с детектором повторных заданий.

    Args:
        dup_radius_mm: Порог невязки трекинга, мм: ниже — «та же деталь».
        dup_window_s:  Окно, сек: сравниваем только с заданиями не старше него.
        maxlen:        Ёмкость кольца строк.
        word_order:    Порядок слов DW (как у клиента/симулятора).
        clock:         Источник времени. Зависимость объекта, а не глобальный
                       патч — иначе тест времени становится флейком.
    """

    def __init__(
        self,
        *,
        dup_radius_mm: float = 5.0,
        dup_window_s: float = 10.0,
        maxlen: int = 4000,
        word_order: str = "little",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dup_radius_mm = dup_radius_mm
        self._dup_window_s = dup_window_s
        self._word_order = word_order
        self._clock = clock
        self._table = _build_decode_table(word_order)
        self._lock = threading.Lock()
        self._pending: deque[JournalEntry] = deque(maxlen=maxlen)
        # Теневая копия регистров, которые ПК пишет — нужна, чтобы в момент
        # job_flag=1 знать координаты задания (они пришли предыдущими записями
        # той же транзакции; сервер применяет их ПОСЛЕ хука, читать живой список
        # нельзя — он ещё старый).
        self._shadow: dict[int, int] = {}
        self._recent_jobs: deque[JobRecord] = deque()
        self.jobs_seen = 0
        self.dups_seen = 0
        self.jobs_done = 0
        self.reads_seen = 0

    # ------------------------------------------------------------------ #
    # Вход: записи с провода
    # ------------------------------------------------------------------ #

    def on_write(self, func_code: int, address: int, values: list[int] | None) -> None:
        """Обработать доступ к регистрам. ``values=None`` — чтение (только счётчик)."""
        if values is None:
            with self._lock:
                self.reads_seen += 1
            return

        now = self._clock()
        with self._lock:
            # 1) тень — до разбора, чтобы job_flag увидел свежие координаты
            for i, raw in enumerate(values):
                self._shadow[address + i] = int(raw) & 0xFFFF
            # 2) строки
            prefix = _FC_NAMES.get(func_code, f"fc{func_code}")
            for i, raw in enumerate(values):
                addr = address + i
                self._pending.append(
                    JournalEntry(now, "in", f"{prefix} {self._name_value(addr, int(raw) & 0xFFFF)}", self._tag_of(addr))
                )
            # 3) взвод задания — считаем и проверяем на дубль
            job_start = address <= REG_JOB_FLAG < address + len(values)
            if job_start and (int(values[REG_JOB_FLAG - address]) & 0xFFFF) == 1:
                self._register_job(now)

    def _name_value(self, address: int, raw: int) -> str:
        """Подписать сырое слово именем из карты (или адресом, если вне карты)."""
        known = self._table.get(address)
        if known is None:
            return f"0x{address:04X} = {raw}"
        name, scale, signed = known
        return f"{name} = {_format_value(raw, scale, signed)}"

    @staticmethod
    def _tag_of(address: int) -> str:
        """Маркер строки: взвод любого mailbox-флага подсвечиваем."""
        return "flag" if address == REG_JOB_FLAG else ""

    def _decode_dw(self, address: int) -> int:
        """Собрать 32-битное значение пары слов из тени (порядок слов — из карты)."""
        words = [self._shadow.get(address, 0), self._shadow.get(address + 1, 0)]
        return decode_int32(words, self._word_order)  # type: ignore[arg-type]

    def _register_job(self, now: float) -> None:
        """Зафиксировать задание и сверить его с недавними (вызывать под локом)."""
        x_mm = decode_int16(self._shadow.get(REG_JOB_X, 0)) / XY_SCALE
        y_mm = decode_int16(self._shadow.get(REG_JOB_Y, 0)) / XY_SCALE
        ecap = self._decode_dw(REG_JOB_ECAP)
        self.jobs_seen += 1
        job = JobRecord(t=now, x_mm=x_mm, y_mm=y_mm, ecap=ecap, index=self.jobs_seen)

        match = self._find_origin(job)
        self._recent_jobs.append(job)
        if match is None:
            self._pending.append(
                JournalEntry(now, "in", f"── ЗАДАНИЕ #{job.index}: pick({x_mm:.1f}, {y_mm:.1f}) e={ecap}", "job")
            )
            return

        prev, residual = match
        self.dups_seen += 1
        self._pending.append(
            JournalEntry(
                now,
                "in",
                f"── ДУБЛЬ #{job.index}: та же деталь, что #{prev.index} "
                f"(невязка {residual:.1f} мм, Δenc={job.ecap - prev.ecap:+d}, "
                f"Δt={job.t - prev.t:.2f} с)",
                "dup",
            )
        )

    def _find_origin(self, job: JobRecord) -> tuple[JobRecord, float] | None:
        """Найти среди недавних заданий то, что описывает ТУ ЖЕ деталь.

        Сравниваем не с одним предыдущим, а со всеми в окне: две детали в кадре
        дают чередование A,B,A' — при сравнении только с соседом дубль A' не
        виден. Возвращает (задание-первоисточник, невязка) или None.
        """
        # Чистим протухшие — окно скользящее, память не растёт.
        while self._recent_jobs and job.t - self._recent_jobs[0].t > self._dup_window_s:
            self._recent_jobs.popleft()
        best: tuple[JobRecord, float] | None = None
        for prev in self._recent_jobs:
            residual = self._residual_mm(prev, job)
            if residual < self._dup_radius_mm and (best is None or residual < best[1]):
                best = (prev, residual)
        return best

    def _residual_mm(self, prev: JobRecord, job: JobRecord) -> float:
        """Невязка трекинга между двумя заданиями, мм.

        Насколько смещение координат РАСХОДИТСЯ с проездом ленты за разницу
        энкодеров. Малая невязка = одна и та же деталь, снятая на разных кадрах;
        большая = разные детали.
        """
        trav = (job.ecap - prev.ecap) * FACTOR_MM
        dx = (job.x_mm - prev.x_mm) - BELT_UX * trav
        dy = (job.y_mm - prev.y_mm) - BELT_UY * trav
        return math.hypot(dx, dy)

    # ------------------------------------------------------------------ #
    # Выход: события ядра
    # ------------------------------------------------------------------ #

    def on_event(self, message: str) -> None:
        """Событие симулятора (зеркало ``print()`` прошивки) → правая колонка."""
        now = self._clock()
        tag = "done" if "выполнено" in message else ""
        with self._lock:
            if tag == "done":
                self.jobs_done += 1
            self._pending.append(JournalEntry(now, "out", message.strip(), tag))

    # ------------------------------------------------------------------ #
    # Потребление
    # ------------------------------------------------------------------ #

    def drain(self) -> list[JournalEntry]:
        """Забрать накопленные строки (журнал очищается)."""
        with self._lock:
            out = list(self._pending)
            self._pending.clear()
        return out

    def counters(self) -> dict[str, int]:
        """Снимок счётчиков для шапки монитора."""
        with self._lock:
            return {
                "jobs": self.jobs_seen,
                "dups": self.dups_seen,
                "done": self.jobs_done,
                "reads": self.reads_seen,
            }

    def reset(self) -> None:
        """Сбросить строки, счётчики и память о последнем задании."""
        with self._lock:
            self._pending.clear()
            self._recent_jobs.clear()
            self.jobs_seen = self.dups_seen = self.jobs_done = self.reads_seen = 0
