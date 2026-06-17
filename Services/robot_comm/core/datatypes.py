"""Типы данных robot_comm (Dict at Boundary: наружу процессов — to_dict)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class RobotPosition:
    """Текущая поза инструмента (главное для калибровки)."""

    x_mm: float
    y_mm: float
    z_mm: float
    rz_deg: float

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Telemetry:
    """Телеметрия робота — блок 0x1130 (11 слов, universal3).

    ВНИМАНИЕ: heartbeat пишется Lua только в idle CVT-ветке — во время job/draw
    телеметрия «стоит», это норма, не обрыв связи. Индикатор «связь жива» —
    по успешности Modbus-чтений, не по этому полю.
    """

    x_mm: float
    y_mm: float
    z_mm: float
    rz_deg: float
    moving: bool
    spd_pct: int
    belt_mm_s: int
    heartbeat: int
    servo: bool
    hand: int
    miss_count: int

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)

    @property
    def position(self) -> RobotPosition:
        """Срез позы из телеметрии."""
        return RobotPosition(self.x_mm, self.y_mm, self.z_mm, self.rz_deg)


@dataclass(slots=True, frozen=True)
class JobEcho:
    """Эхо последнего принятого CVT-задания (блок 0x1120)."""

    job_x: float
    job_y: float
    px: float
    py: float
    trav: float

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)


@dataclass(slots=True, frozen=True)
class DrawPoint:
    """Точка пути рисования: координаты + состояние пера (1 = опущено)."""

    x_mm: float
    y_mm: float
    pen: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)


# Буфер робота на ОДИН проход (= PTS_MAX в registers.py и в cvt_universal_full.lua).
# Путь длиннее рисуется несколькими проходами; здесь дефолт для split_draw_passes.
DEFAULT_PASS_LIMIT = 100


def split_draw_passes(points: list[DrawPoint], limit: int = DEFAULT_PASS_LIMIT) -> list[list[DrawPoint]]:
    """Разбить путь на проходы ≤ ``limit`` точек, НЕ обрывая штрих посреди.

    Робот рисует проход за проходом; в конце КАЖДОГО прохода поднимает перо и едет
    домой (execute_path в cvt_universal_full.lua → перо вверх + MovP("GL_HOME")).
    Чтобы при возобновлении не появлялась паразитная линия «от дома» и не терялись
    штрихи, проход обязан начинаться с подвода (pen=0) и не рваться внутри штриха.

    Поэтому режем ТОЛЬКО на границах штрихов (точки pen=0). Если ОДИН штрих длиннее
    ``limit`` — режем принудительно, вставляя в точку возобновления подвод (pen=0):
    робот доедет туда с поднятым пером и продолжит ровно с той же точки (линия не
    теряется, добавляется лишь холостой ход).

    Пустой вход → пустой список. Чистая функция (без I/O) — переиспользуется превью.
    """
    if limit < 3:
        raise ValueError(f"limit прохода: ожидается ≥ 3, получено {limit}")
    if not points:
        return []

    # Инвариант: путь ОБЯЗАН начинаться с подвода (pen=0), иначе робот чертил бы линию «от
    # дома» к первой точке. Все живые продюсеры так и делают, но загруженный из файла JSON
    # или внешний путь могут начать с pen=1 — нормализуем явно (без молчаливого контракта).
    if points[0].pen != 0:
        points = [DrawPoint(points[0].x_mm, points[0].y_mm, 0), *points[1:]]

    # 1) Сгруппировать точки в штрихи: штрих = подвод (pen=0) + точки рисования (pen=1)
    #    до следующего подвода. Первый штрих может начинаться не с pen=0 — берём как есть.
    strokes: list[list[DrawPoint]] = []
    cur: list[DrawPoint] = []
    for p in points:
        if p.pen == 0 and cur:
            strokes.append(cur)
            cur = []
        cur.append(p)
    if cur:
        strokes.append(cur)

    # 2) Упаковать штрихи в проходы ≤ limit, не разрывая (кроме штриха длиннее limit).
    passes: list[list[DrawPoint]] = []
    batch: list[DrawPoint] = []
    for stroke in strokes:
        if len(stroke) > limit:
            if batch:
                passes.append(batch)
                batch = []
            passes.extend(_split_long_stroke(stroke, limit))
            continue
        if batch and len(batch) + len(stroke) > limit:
            passes.append(batch)
            batch = []
        batch.extend(stroke)
    if batch:
        passes.append(batch)
    return passes


def _split_long_stroke(stroke: list[DrawPoint], limit: int) -> list[list[DrawPoint]]:
    """Штрих длиннее буфера → куски ≤ limit; возобновление с подводом (pen=0) + OVERLAP 1.

    Между проходами робот поднимает перо (финал прохода). Поэтому кусок обязан
    возобновляться с подвода (pen=0) — иначе робот чертил бы линию «от дома». РАНЬШЕ
    подвод ставился в stroke[i], а предыдущий кусок заканчивался на stroke[i-1] → сегмент
    stroke[i-1]→stroke[i] НЕ рисовался (терялся один сегмент на КАЖДОЙ границе прохода).

    Теперь возобновляем с ПОСЛЕДНЕЙ точки предыдущего куска (overlap 1): подвод pen=0 к
    stroke[i-1], опускание и ПЕРЕ-рисовка граничного сегмента — линия остаётся непрерывной.
    Исходные точки не теряются (добавляются лишь подвод + дубль граничной точки).
    Требует limit ≥ 3 (кусок вмещает подвод + ≥2 точки для сегмента).
    """
    chunks: list[list[DrawPoint]] = [stroke[:limit]]
    i = limit
    while i < len(stroke):
        prev = stroke[i - 1]  # точка стыка = последняя нарисованная в предыдущем куске
        anchor = DrawPoint(prev.x_mm, prev.y_mm, 0)  # подвод к стыку (перо вверх)
        chunks.append([anchor, *stroke[i - 1 : i - 1 + (limit - 1)]])  # пере-включаем стык
        i += limit - 2  # overlap 1 точку → граничный сегмент рисуется
    return chunks
