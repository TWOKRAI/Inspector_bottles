"""Программы робота: точки, системы координат, шаги и компиляция в сценарий (protocol-spec §7).

Purpose: описать программу робота смыслом (точки в мм и °, СК, ходы и действия по именам) и
скомпилировать её в `Scenario` — список записей в базе с индекс-картой «запись → шаг программы».
Программы не знают провода: упаковка записи в регистры, квантование ×0.1, `SC_CAP`, куски
пинг-понга и `SC_RUN` — забота клиента (T3.1/T3.2). Геометрия — только через `programs.geometry`.

Public API: `Point`, `FrameDef`, `Move`, `Action`, `Program`, `Record`, `Scenario`,
`CompileError`, `compile_program`.

Stability: lite
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ACT, KIND, REASON, REASON_TEXT
from Services.robot_comm.programs import geometry

__all__ = [
    "Action",
    "CompileError",
    "FrameDef",
    "Move",
    "Point",
    "Program",
    "Record",
    "Scenario",
    "compile_program",
]


def _strict_coord(v: Any) -> float:
    """Координата на границе (YAML, `from_dict`): int или float, конечная; bool и строки не приводятся."""
    if type(v) not in (int, float) or not math.isfinite(v):
        raise ValueError("координата — конечное число (int или float)")
    return float(v)


type Coord = Annotated[float, BeforeValidator(_strict_coord)]
type Triple = tuple[Coord, Coord, Coord]

_ACC_META = PARAMS[PARAM_ID["P_ACC_L"]]

# Диапазон APARAM по действию (включительно). Литералы DO/SPEED/ACCUR повторяют проверку прошивки и sim
# (`server/sim_core_v2.py`, `_sc_validate`), ACCEL — метаданные `P_ACC_L`; перенос в `delta_v2.yaml` —
# отдельной задачей (О3 брифа T3.3). Имя из `ACT` без строки здесь — ошибка «нет диапазона».
_ACT_RANGE: dict[str, tuple[int, int]] = {
    "DO_ON": (1, 16),  # канал
    "DO_OFF": (1, 16),  # канал
    "DELAY_MS": (0, 65535),  # мс, весь u16
    "SPEED_PCT": (1, 100),  # %
    "ACCEL": (int(_ACC_META["min"]), int(_ACC_META["max"])),  # мм/с²
    "ACCUR": (0, 1),
}


def _check_aparam(act: str, value: int) -> None:
    """Параметр действия по таблице `_ACT_RANGE`; `NONE` — только 0. Общая проверка `Action` и `Record`."""
    if act == "NONE":
        if value != 0:
            raise ValueError("у записи без действия параметр должен быть 0")
        return
    bounds = _ACT_RANGE.get(act)
    if bounds is None:
        raise ValueError("нет диапазона параметра для этого действия (новый код ACT без строки таблицы)")
    lo, hi = bounds
    if not lo <= value <= hi:
        raise ValueError(f"параметр действия вне диапазона {lo}..{hi}")


class _Model(BaseModel):
    """База моделей пакета: неизменяемые, без лишних полей, входное значение не попадает в текст ошибки."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    def to_dict(self) -> dict[str, Any]:
        """Модель → словарь из JSON-типов (имена `KIND`/`ACT` — строки)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        """Словарь → модель с полной валидацией (обратно `to_dict`)."""
        return cls.model_validate(d)


class Point(_Model):
    """Обученная точка: мм и °; `frame=None` — база; `hand` — 0 правая / 1 левая (как `P_HAND`)."""

    name: Annotated[str, Field(min_length=1)]
    x: Coord
    y: Coord
    z: Coord
    rz: Coord
    hand: Literal[0, 1]
    frame: str | None = None

    @field_validator("hand", mode="before")
    @classmethod
    def _hand_strict(cls, v: Any) -> Any:
        # Точки приходят из YAML, правленного руками: True/1.0/"1" молча в руку не приводим.
        if type(v) is not int or v not in (0, 1):
            raise ValueError("рука — целое 0 (правая) или 1 (левая)")
        return v


class FrameDef(_Model):
    """СК по трём точкам базы: начало, точка на оси X, точка в плоскости XY. Математика — `geometry.Frame`."""

    name: str
    origin: Triple
    on_x: Triple
    in_plane: Triple

    @model_validator(mode="after")
    def _non_degenerate(self) -> Self:
        # ValueError геометрии (вырожденные точки) pydantic превращает в ошибку валидации.
        self._geometry()
        return self

    def _geometry(self) -> geometry.Frame:
        # Без кэша: `model_copy(update=...)` не валидирует, кэш остался бы от старых точек.
        return geometry.Frame.from_points(self.origin, self.on_x, self.in_plane)

    def to_base(self, x: float, y: float, z: float, rz: float) -> tuple[float, float, float, float]:
        """Точка СК → база."""
        return self._geometry().to_base(x, y, z, rz)

    def from_base(self, x: float, y: float, z: float, rz: float) -> tuple[float, float, float, float]:
        """Точка базы → СК (обратно `to_base`)."""
        return self._geometry().from_base(x, y, z, rz)


class Move(_Model):
    """Шаг «ход в точку `point`» видом `kind` (ключ `KIND`)."""

    op: Literal["move"] = "move"
    point: str
    kind: str

    @field_validator("kind")
    @classmethod
    def _kind_known(cls, v: str) -> str:
        if v not in KIND:
            raise ValueError(f"неизвестный вид хода; допустимы: {', '.join(KIND)}")
        return v


class Action(_Model):
    """Шаг «действие `act` с параметром `value`» — исполняется после прихода в предыдущую точку."""

    op: Literal["act"] = "act"
    act: str
    value: StrictInt

    @field_validator("act")
    @classmethod
    def _act_known(cls, v: str) -> str:
        if v not in ACT or v == "NONE":
            raise ValueError(f"неизвестное действие; допустимы: {', '.join(a for a in ACT if a != 'NONE')}")
        return v

    @model_validator(mode="after")
    def _value_in_range(self) -> Self:
        _check_aparam(self.act, self.value)
        return self


type Step = Annotated[Move | Action, Field(discriminator="op")]


class Program(_Model):
    """Хранимая программа: версия формата, имя, шаги по порядку."""

    version: Literal[1] = 1
    name: str
    steps: tuple[Step, ...]

    @field_validator("version", mode="before")
    @classmethod
    def _version_supported(cls, v: Any) -> Any:
        if type(v) is not int or v != 1:
            raise ValueError("версия формата программы не поддерживается: ожидается 1, миграций нет")
        return v


class Record(_Model):
    """Запись сценария в базе: мм и °, вид хода и действие — имена-ключи `KIND`/`ACT`."""

    x: Coord
    y: Coord
    z: Coord
    rz: Coord
    kind: str
    action: str
    aparam: StrictInt

    @field_validator("kind")
    @classmethod
    def _kind_known(cls, v: str) -> str:
        if v not in KIND:
            raise ValueError(f"неизвестный вид хода; допустимы: {', '.join(KIND)}")
        return v

    @field_validator("action")
    @classmethod
    def _action_known(cls, v: str) -> str:
        if v not in ACT:
            raise ValueError(f"неизвестное действие; допустимы: {', '.join(ACT)}")
        return v

    @model_validator(mode="after")
    def _aparam_in_range(self) -> Self:
        _check_aparam(self.action, self.aparam)
        return self


class Scenario(_Model):
    """Результат компиляции: записи и `step_of[i]` — индекс шага программы, породившего запись i."""

    records: tuple[Record, ...]
    step_of: tuple[Annotated[StrictInt, Field(ge=0)], ...]

    @model_validator(mode="after")
    def _same_length(self) -> Self:
        if len(self.step_of) != len(self.records):
            raise ValueError("длины records и step_of не совпадают")
        return self


class CompileError(ValueError):
    """Отказ компиляции: `step` — индекс шага программы, `reason` — код `REASON` (0 — уровень программы)."""

    def __init__(self, step: int, reason: int, text: str) -> None:
        super().__init__(text)
        self.step = step
        self.reason = reason
        self.text = text

    def __reduce__(self) -> tuple[type[CompileError], tuple[int, int, str]]:
        # Три аргумента конструктора при args=(text,): без этого pickle.loads падает с TypeError.
        return (type(self), (self.step, self.reason, self.text))


def _fail(step: int, reason: int, what: str = "") -> CompileError:
    """Ошибка без входных значений: индекс шага и текст причины (`REASON_TEXT` либо `what` для кода 0)."""
    return CompileError(step, reason, f"шаг {step}: {REASON_TEXT[reason] if reason else what}")


def compile_program(
    program: Program,
    points: Mapping[str, Point],
    frames: Mapping[str, FrameDef],
    params: Mapping[str, float],
) -> Scenario:
    """Компилирует программу в `Scenario`; первая ошибка в порядке шагов → `CompileError`.

    `params` — инженерные значения `P_WS_*` (как у `Workspace.from_params`) и `P_HAND`. Чистая
    функция: без состояния и I/O. Внутри `Move` порядок проверок: неизвестная точка или СК (0) →
    последний `Move` LINE_PASS (6) → точка (4) → рука (7) → отрезок LINE/LINE_PASS (5 или 4).
    """
    ws = geometry.Workspace.from_params(params)
    p_hand = params["P_HAND"]
    moves = [i for i, step in enumerate(program.steps) if isinstance(step, Move)]
    last_move = moves[-1] if moves else None
    records: list[dict[str, Any]] = []
    step_of: list[int] = []

    for i, step in enumerate(program.steps):
        if isinstance(step, Move):
            point = points.get(step.point)
            if point is None:
                raise _fail(i, 0, "неизвестная точка")
            if point.frame is None:
                x, y, z, rz = point.x, point.y, point.z, point.rz
            else:
                frame = frames.get(point.frame)
                if frame is None:
                    raise _fail(i, 0, "неизвестная СК")
                x, y, z, rz = frame.to_base(point.x, point.y, point.z, point.rz)
            if i == last_move and step.kind == "LINE_PASS":
                raise _fail(i, REASON["R_LAST_PASS"])
            reason = geometry.check_point(ws, x, y, z, rz)
            if reason:
                raise _fail(i, reason)
            if point.hand != p_hand:
                raise _fail(i, REASON["R_HAND"])
            if records and step.kind != "JOINT":
                prev = records[-1]
                reason = geometry.check_segment(ws, prev["x"], prev["y"], x, y)
                if reason:
                    raise _fail(i, reason)
            records.append({"x": x, "y": y, "z": z, "rz": rz, "kind": step.kind, "action": "NONE", "aparam": 0})
            step_of.append(i)
            continue

        if not records:
            raise _fail(i, 0, "действие до первого хода")
        prev = records[-1]
        if prev["action"] == "NONE" and prev["kind"] != "LINE_PASS":
            prev["action"], prev["aparam"] = step.act, step.value
        else:
            # Дубль-запись стоит в координатах prev: точка уже прошла check_point, нулевой отрезок
            # prev→prev лежит на r >= r_min и в секторе — повторная проверка ничего не добавит.
            records.append({**prev, "kind": "LINE", "action": step.act, "aparam": step.value})
            step_of.append(i)

    if last_move is None:
        raise _fail(0, 0, "в программе нет ни одного хода")
    return Scenario(records=tuple(Record(**r) for r in records), step_of=tuple(step_of))
