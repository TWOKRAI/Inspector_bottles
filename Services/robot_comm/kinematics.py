"""Модель робота (T2.K, `plans/robot-protocol-v2/tasks.md`) — прямая/обратная
кинематика и цепочка звеньев, за интерфейсом `RobotModel`.

Робот сменного типа: сегодня SCARA (`ScaraModel`, закрытая формула ниже), но
контракт рассчитан на замену. Три слоя, которые меняются НЕЗАВИСИМО друг от
друга:

1. **Поле протокола** (`TLM_HAND`/`P_HAND` и т.п., `core/protocol_v2.py`,
   `core/params_v2.py`) — что лежит в проводе, не трогается этим модулем.
2. **`RobotModel`** (этот файл) — как поза переводится в суставы и обратно.
3. **Ширина позы** — сегодня `(x, y, z, rz)`, 4 канала. 6-осевая рука добавит
   `(rx, ry)` — расширение позы, а не замена интерфейса `RobotModel`.

Решение владельца от 2026-09-27: SCARA — закрытой формулой прямо здесь
(`ScaraModel`), сейчас. 6-осевая рука позже — `roboticstoolbox-python`
(численный IK, DH-параметры) за тем же `RobotModel.fk/ik`. Дельта-робот —
уравнения Кляве (Clavel) за тем же интерфейсом, когда он понадобится. RX/RY
осмысленны только при 6-осевой прошивке — сегодняшняя v2 их не несёт.

Модуль Qt-independent, состояния не хранит, зависит только от stdlib
`math` (без numpy — SCARA IK/FK это несколько тригонометрических формул, не
повод тащить зависимость).

`check_point`/`check_segment` модели — чистое делегирование в
`programs/geometry.py` (И6 протокола: вторая правда о достижимости не
заводится, geometry.py остаётся единственным источником, зеркалит прошивку).
"""

from __future__ import annotations

import math
import typing
from dataclasses import dataclass, fields

from Services.robot_comm.programs import geometry
from Services.robot_comm.programs.geometry import check_point, check_segment

Pose = tuple[float, float, float, float]
Joints = tuple[float, ...]
#: одна ломаная (полилиния) точек звеньев одной кинематической цепи.
Chain = list[tuple[float, float, float]]

#: допуск на границе досягаемости (float-шум сложения квадратов длин звеньев).
_REACH_TOL = 1e-9


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _wrap_deg(angle: float) -> float:
    """Оборачивает угол (градусы) в `(-180, 180]` — диапазон, в котором реальный
    контроллер репортует суставы. `fmod` — не `%`: даёт знак результата "как у
    делимого", формула ниже компенсирует это явным сдвигом на 180°/360°."""
    wrapped = math.fmod(angle - 180.0, 360.0)
    if wrapped <= 0.0:
        wrapped += 360.0
    return wrapped - 180.0


class RobotModel(typing.Protocol):
    """Контракт кинематической модели робота — единственная точка замены типа руки.

    `hand` — код конфигурации руки, СВОЙ у каждой модели (SCARA: 0 правая / 1
    левая; 6-осевая рука: битовая маска плечо/локоть/кисть; дельта Клавеля код
    не использует). Значение вне допустимого множества модели -> `ValueError`
    у конкретной реализации (не тихая подстановка "как будто 0").
    """

    kind: str
    axes: tuple[str, ...]
    joint_names: tuple[str, ...]

    def fk(self, joints: Joints) -> Pose | None: ...

    def ik(self, pose: Pose, hand: int) -> Joints | None: ...

    def chain_points(self, joints: Joints) -> list[Chain]: ...

    def check_point(self, ws: geometry.Workspace, pose: Pose) -> int: ...

    def check_segment(self, ws: geometry.Workspace, p0: Pose, p1: Pose) -> int: ...


@dataclass(frozen=True)
class ScaraModel:
    """SCARA с двумя звеньями, закрытая формула FK/IK (plans/robot-protocol-v2 §9 q1).

    Суставы — кортеж ``(J1, J2, Z, J4)`` в градусах/мм (J1/J2/J4 — углы,
    Z — линейная ось). Поза — ``(x, y, z, rz)`` в мм/градусах.
    """

    # ponytail: длины звеньев — заглушка (P_WS_R_MAX по умолчанию = 600 = l1+l2),
    # реальные значения — с шильдика робота, plan §9 q1.
    l1: float = 325.0
    l2: float = 275.0

    kind: typing.ClassVar[str] = "scara"
    axes: typing.ClassVar[tuple[str, ...]] = ("X", "Y", "Z", "RZ")
    joint_names: typing.ClassVar[tuple[str, ...]] = ("J1", "J2", "Z", "J4")

    def __post_init__(self) -> None:
        """Dict at Boundary (`make_model` собирает `ScaraModel` из словаря spec) —
        длины звеньев валидируются здесь, а не молча дают `ZeroDivisionError`/
        `TypeError` в `fk`/`ik` при первом использовании."""
        for name, value in (("l1", self.l1), ("l2", self.l2)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} должен быть конечным числом > 0, получено {value!r}")

    def fk(self, joints: Joints) -> Pose:
        """Прямая кинематика: суставы -> поза. RZ = J1 + J2 + J4 (contract §"Motion model").

        Для SCARA (последовательная цепь из 2 звеньев) FK тотальна — любой
        набор суставов даёт позу, `None` никогда не возвращается (в отличие
        от общего контракта `RobotModel.fk`, где дельта-FK может не иметь
        решения для части троек углов).
        """
        j1, j2, z, j4 = joints
        j1r = math.radians(j1)
        j2r = math.radians(j2)
        x = self.l1 * math.cos(j1r) + self.l2 * math.cos(j1r + j2r)
        y = self.l1 * math.sin(j1r) + self.l2 * math.sin(j1r + j2r)
        return (x, y, z, j1 + j2 + j4)

    def ik(self, pose: Pose, hand: int) -> Joints | None:
        """Обратная кинематика: поза -> суставы, `None` если точка вне досягаемости.

        ⚑ GATE-1: знак руки — ``hand=0`` (правая) даёт ``J2 >= 0``
        (``J2 = +acos(c2)``), ``hand=1`` (левая) даёт ``J2 <= 0``
        (``J2 = -acos(c2)``). `c2` зажимается в `[-1, 1]` ПОСЛЕ проверки
        досягаемости — на границе (`r == l1+l2`) float-сумма квадратов может
        дать `c2` чуть больше 1, `acos` без зажима упал бы `ValueError`.
        `hand` — код конфигурации SCARA, ровно `{0, 1}`; любое другое
        значение -> `ValueError` (молчаливая подстановка "как правая" —
        источник необнаружимой ошибки в проводке).

        `J1` нормализуется в `(-180, 180]` (`_wrap_deg`) — так репортует
        реальный контроллер. `J4 = RZ - J1 - J2` считается ПОСЛЕ этой
        нормализации, от уже обёрнутого `J1` — поэтому `fk(ik(pose))`
        возвращает RZ побитово точным входному (не по модулю 360°), какой бы
        оборот ни потребовался `J1`. `J4` сознательно НЕ оборачивается тем же
        способом: пост-hoc обёртка `J4` сдвинула бы сумму `J1+J2+J4` в `fk` на
        кратное 360° и сломала бы эту точность (воспроизведено на приёмочной
        сетке T2.K: 28/238 случаев дают `|J4| > 180`, обёртка изменила бы
        `fk(...)  [3]` на `RZ ± 360·k`). Если реальному контроллеру нужен J4
        в одном обороте — оборачивать только для отображения, не для
        обратной подстановки в `fk`.
        """
        if hand not in (0, 1):
            raise ValueError(f"hand должен быть 0 (правая) или 1 (левая) для SCARA, получено {hand!r}")
        x, y, z, rz = pose
        if not all(math.isfinite(v) for v in pose):
            return None
        r = math.hypot(x, y)
        reach_min = abs(self.l1 - self.l2)
        reach_max = self.l1 + self.l2
        if r > reach_max + _REACH_TOL or r < reach_min - _REACH_TOL:
            return None
        c2 = _clamp((r * r - self.l1 * self.l1 - self.l2 * self.l2) / (2 * self.l1 * self.l2), -1.0, 1.0)
        j2 = math.degrees(math.acos(c2))
        if hand == 1:
            j2 = -j2
        j2r = math.radians(j2)
        j1 = math.degrees(math.atan2(y, x) - math.atan2(self.l2 * math.sin(j2r), self.l1 + self.l2 * math.cos(j2r)))
        j1 = _wrap_deg(j1)
        j4 = rz - j1 - j2
        return (j1, j2, z, j4)

    def chain_points(self, joints: Joints) -> list[Chain]:
        """Точки звеньев для отрисовки: одна ломаная (SCARA — последовательная
        цепь) база (ось J1) -> локоть -> инструмент.

        Возвращает список ломаных (`list[Chain]`), а НЕ плоский список точек:
        общий контракт `RobotModel.chain_points` должен различать одну
        последовательную цепь (SCARA/6-осевая — одна ломаная) от нескольких
        параллельных (дельта Клавеля — три ломаные база_i->локоть_i->платформа_i);
        плоский список неотличим от третьего варианта и рисовал бы фантомные
        звенья между цепями. SCARA — всегда `[[base, elbow, tool]]`, одна цепь.

        Z всех трёх точек — Z позы (SCARA поднимает/опускает инструмент по
        вертикали, звенья остаются в горизонтальной плоскости текущего Z).
        """
        j1, _j2, z, _j4 = joints
        j1r = math.radians(j1)
        base = (0.0, 0.0, z)
        elbow = (self.l1 * math.cos(j1r), self.l1 * math.sin(j1r), z)
        x, y, _z, _rz = self.fk(joints)
        tool = (x, y, z)
        return [[base, elbow, tool]]

    def check_point(self, ws: geometry.Workspace, pose: Pose) -> int:
        """Делегирует в `geometry.check_point` — вторая правда о зоне не заводится (И6)."""
        return check_point(ws, *pose)

    def check_segment(self, ws: geometry.Workspace, p0: Pose, p1: Pose) -> int:
        """Делегирует в `geometry.check_segment` — вторая правда о зоне не заводится (И6)."""
        return check_segment(ws, p0[0], p0[1], p1[0], p1[1])


_MODELS: dict[str, type] = {"scara": ScaraModel}


def make_model(spec: dict) -> RobotModel:
    """Строит модель робота из словаря спецификации (`{"type": "scara", "l1"?, "l2"?}`).

    Dict at Boundary: неизвестный `type` или неизвестный ключ параметра ->
    `ValueError` с именем проблемного значения/ключа — НЕ `TypeError` из
    конструктора датакласса (тот не называет источник, если spec пришёл
    снаружи процесса десериализованным из JSON/YAML).
    """
    kind = spec.get("type")
    cls = _MODELS.get(kind)
    if cls is None:
        known = ", ".join(sorted(_MODELS))
        raise ValueError(f"неизвестный тип робота {kind!r}; известные: {known}")
    kwargs = {k: v for k, v in spec.items() if k != "type"}
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise ValueError(f"неизвестные параметры модели {unknown} для типа {kind!r}; допустимые: {sorted(allowed)}")
    return cls(**kwargs)
