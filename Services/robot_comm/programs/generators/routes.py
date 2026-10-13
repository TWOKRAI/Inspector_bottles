"""Генераторы маршрутов: возврат детали в слот и смена инструмента (T3.4; v1 RETURN и TOOLCHANGE).

Purpose: построить программы T3.3 по маршрутам v1 (`robot/main_actual.lua`: `run_return`,
`tool_remove`/`tool_mount`) с правилами v2: первый ход JOINT (или JOINT в `approach`, ответ В1),
действия только после EXACT-ходов, `home` — последним ходом JOINT (ответ В2).

Public API: `return_slot`, `toolchange`, `TOOL_POINTS_V1`, `TRANSIT_V1`.

Stability: lite
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from Services.robot_comm.programs import Point
from Services.robot_comm.programs.generators._common import GeneratedProgram, GeneratorError, _Builder

__all__ = ["TOOL_POINTS_V1", "TRANSIT_V1", "return_slot", "toolchange"]

# (над инструментом, гнездо, выход) по номеру инструмента — имена точек v1 (`main_actual.lua:767-770`).
TOOL_POINTS_V1: Mapping[int, tuple[str, str, str]] = MappingProxyType(
    {1: ("t1_over", "t1_pick", "t1_exit"), 2: ("t2_over", "t2_pick", "t2_exit")}
)
# Транзит: инструмент 2 всегда через «над 1» (`main_actual.lua:771`).
TRANSIT_V1: Mapping[int, str] = MappingProxyType({2: "t1_over"})


def return_slot(
    slot: Point,
    *,
    lift_mm: float = 20.0,
    push_dx_mm: float = 100.0,
    push_dy_mm: float = 0.0,
    grip_do: int = 1,
    grip_delay_ms: int = 400,
    name: str = "return_slot",
    approach: Point | None = None,
    home: Point | None = None,
) -> GeneratedProgram:
    """Возврат детали из слота на ленту (v1 RETURN, `run_return`): над слотом → захват → подъём → сдвиг → отпуск.

    Все точки — в СК `slot.frame`, рука `slot.hand`, RZ `slot.rz`; подъём и сдвиг — в координатах этой
    СК. Умолчания из v1: `RET_LIFT_MM` 20, `RET_PUSH_MM` 100 по +X, `DO_GRIP` 1, `GRIP_S` 0.4 с.

    Pre: `lift_mm > 0` — иначе `GeneratorError`; канал и задержка в диапазоне `Action` — иначе
    `ValueError` валидации.
    Post: без `approach` первый ход — JOINT над слотом, с `approach` — JOINT в `approach`, и весь маршрут
    LINE; действия DO_ON/DO_OFF и DELAY_MS — только после EXACT-ходов; с `home` последний ход — JOINT в
    `home`. Зону и руку проверяет вызывающий через `compile_program`.
    """
    if not lift_mm > 0:
        raise GeneratorError("подъём над слотом должен быть больше 0")
    b = _Builder(name)
    first = "JOINT"
    if approach is not None:
        b.move_ref(approach, "JOINT")
        first = "LINE"
    sx, sy, sz, top = slot.x, slot.y, slot.z, slot.z + lift_mm
    px, py = sx + push_dx_mm, sy + push_dy_mm

    def p(x: float, y: float, z: float, kind: str) -> None:
        b.move_new(x, y, z, slot.rz, hand=slot.hand, frame=slot.frame, kind=kind)

    p(sx, sy, top, first)  # над слотом
    p(sx, sy, sz, "LINE")
    b.act("DO_ON", grip_do)
    b.act("DELAY_MS", grip_delay_ms)
    p(sx, sy, top, "LINE")  # подъём
    p(px, py, top, "LINE")  # сдвиг к ленте
    p(px, py, sz, "LINE")
    b.act("DO_OFF", grip_do)
    b.act("DELAY_MS", grip_delay_ms)
    if home is not None:
        b.move_ref(home, "JOINT")
    return b.build()


type _Step = tuple[str, str, int]  # ("move", имя точки, 0) или ("act", действие, значение)


def _route(
    current: int,
    target: int,
    tools: Mapping[int, tuple[str, str, str]],
    transit: Mapping[int, str],
    seat_delay_ms: int,
) -> list[_Step]:
    """Маршрут смены v1 (`tool_remove`, затем `tool_mount`) шагами `_Step`; повторные ходы ещё не убраны."""
    out: list[_Step] = []
    if current:
        over, sock, exit_ = tools[current]
        out += [("move", exit_, 0), ("act", "ACCUR", 1), ("move", sock, 0), ("act", "DELAY_MS", seat_delay_ms)]
        out += [("act", "ACCUR", 0), ("move", over, 0)]
        if current in transit:
            out.append(("move", transit[current], 0))
    if target:
        over, sock, exit_ = tools[target]
        if target in transit:
            out.append(("move", transit[target], 0))
        out += [("move", over, 0), ("act", "ACCUR", 1), ("move", sock, 0), ("act", "DELAY_MS", seat_delay_ms)]
        out += [("act", "ACCUR", 0), ("move", exit_, 0)]
    return out


def toolchange(
    current: int,
    target: int,
    points: Mapping[str, Point],
    *,
    tools: Mapping[int, tuple[str, str, str]] = TOOL_POINTS_V1,
    transit: Mapping[int, str] = TRANSIT_V1,
    seat_delay_ms: int = 1000,
    name: str = "toolchange",
    approach: Point | None = None,
    home: Point | None = None,
) -> GeneratedProgram:
    """Смена инструмента (v1 TOOLCHANGE): снять `current`, потом надеть `target`; 0 — «без инструмента».

    `points` — библиотека обученных точек вызывающего; новых точек генератор не создаёт. Снять n:
    выход, ACCUR 1, гнездо, пауза `seat_delay_ms`, ACCUR 0, над, [транзит]; надеть n — обратный порядок
    с транзитом в начале. `ACCUR 1` = v1 `Accur("HIGH")`, `ACCUR 0` = `Accur("ROUGH")`.

    Pre: current == target — ошибка; вызывающий проверяет сам (в v1 — успех без движения).
    Номер не 0 и не ключ `tools` → `GeneratorError` «неизвестный номер инструмента»; нет точек маршрута
    в `points` → одна `GeneratorError` «обучите точки: …» со всеми недостающими именами по алфавиту.
    Post: первый ход — JOINT в первую точку маршрута (с `approach` — JOINT в `approach`, весь маршрут
    LINE); повторный ход в ту же точку подряд (стык «снять 1 → надеть 2») пропущен; с `home` последний
    ход — JOINT в `home`. Зону и руку проверяет вызывающий через `compile_program`.
    """
    for n in (current, target):
        if n != 0 and n not in tools:
            raise GeneratorError("неизвестный номер инструмента")
    if current == target:
        raise GeneratorError("инструмент уже установлен — смена не нужна")
    route = _route(current, target, tools, transit, seat_delay_ms)
    missing = sorted({what for op, what, _ in route if op == "move" and what not in points})
    if missing:
        raise GeneratorError(f"обучите точки: {', '.join(missing)}")

    b = _Builder(name)
    kind = "JOINT"
    if approach is not None:
        b.move_ref(approach, "JOINT")
        kind = "LINE"
    started = False
    for op, what, value in route:
        if op == "act":
            b.act(what, value)
            continue
        if started and b.last_move_name() == what:
            continue  # повторный ход в ту же точку без действий между — ход нулевой длины
        b.move_ref(points[what], kind)
        kind, started = "LINE", True
    if home is not None:
        b.move_ref(home, "JOINT")
    return b.build()
