"""Слепая property-приёмка T3.3: программы робота -> сценарий (protocol-spec §7).

Purpose: закрепить контракт пакета ``Services.robot_comm.programs`` независимыми оракулами (зона §7.3,
расстояние от оси J1 до отрезка, плоские СК с известным поворотом) до того, как пакет написан:
круг «программа -> записи -> обратно» (±0.05), тождество СК -> база -> СК, ни одной записи вне зоны,
ни одного LINE-отрезка через мёртвую зону, биекция «шаг движения -> запись», последняя запись не LINE_PASS.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite

Допущения (что тесты принимают на веру):
  A1  API и имена полей — как в плане и брифе T3.3.tester: ``Point``, ``FrameDef``, ``Move``, ``Action``,
      ``Program``, ``Scenario``, ``compile_program``, ``CompileError``; конструкторы — по именам.
  A2  Записи ``Scenario.records`` хранят миллиметры и градусы без грубого округления (допуск ±0.05).
  A3  Точки без СК (``frame=None``) попадают в записи без изменений.
  A4  RZ не нормируется по кругу: RZ в базе = RZ в СК + угол оси X СК (см. свойство a).
  A5  Порядок проверок внутри одного ``Move``: неизвестная точка -> последний Move LINE_PASS (6) ->
      точка вне зоны (4) -> рука (7) -> отрезок (5).
Импорт пакета — в ``_api()`` внутри тела теста: до кода пакета каждый тест краснеет отдельно, сборка файла цела.
Коды причин (4, 5, 6) записаны литералами: ``REASON`` не импортируется.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

__all__: list[str] = []

# --- Литералы параметров (мм, °) — protocol-spec §7.3 ------------------------------------------------------
PARAMS: dict[str, float] = {
    "P_WS_R_MIN": 100.0,
    "P_WS_R_MAX": 600.0,
    "P_WS_Z_MIN": -150.0,
    "P_WS_Z_MAX": 0.0,
    "P_WS_RZ_MIN": -360.0,
    "P_WS_RZ_MAX": 360.0,
    "P_WS_ANG_MIN": -165.0,
    "P_WS_ANG_MAX": 165.0,
    "P_WS_BOX_EN": 0.0,
    "P_WS_X_MIN": -600.0,
    "P_WS_X_MAX": 600.0,
    "P_WS_Y_MIN": -600.0,
    "P_WS_Y_MAX": 600.0,
    "P_HAND": 1.0,
}
KINDS = ("LINE", "LINE_PASS", "JOINT")
ACTION_RANGES = {
    "DO_ON": (1, 16),
    "DO_OFF": (1, 16),
    "DELAY_MS": (0, 65535),
    "SPEED_PCT": (1, 100),
    "ACCEL": (100, 50000),
    "ACCUR": (0, 1),
}
TOL = 0.05 + 1e-9  # допуск круга «программа -> записи -> обратно»

_SETTINGS = settings(max_examples=200, deadline=None, derandomize=True)


# --- Доступ к пакету (импорт только здесь) ------------------------------------------------------------------
def _api() -> SimpleNamespace:
    from Services.robot_comm.programs import (
        Action,
        CompileError,
        FrameDef,
        Move,
        Point,
        Program,
        Scenario,
        compile_program,
    )

    return SimpleNamespace(
        Action=Action,
        CompileError=CompileError,
        FrameDef=FrameDef,
        Move=Move,
        Point=Point,
        Program=Program,
        Scenario=Scenario,
        compile_program=compile_program,
    )


def _point(api: SimpleNamespace, name: str, x: float, y: float, z: float, rz: float, frame: str | None = None):
    return api.Point(name=name, x=x, y=y, z=z, rz=rz, hand=1, frame=frame)


def _run(api: SimpleNamespace, steps: list, points: dict, frames: dict | None = None):
    program = api.Program(name="acceptance", steps=tuple(steps))
    return api.compile_program(program, points, frames or {}, dict(PARAMS))


# --- Оракулы (свои, по protocol-spec §7.3; не из кода под тестом) --------------------------------------------
def _in_zone(x: float, y: float, z: float, rz: float) -> bool:
    r2 = x * x + y * y
    if not (100.0**2 <= r2 <= 600.0**2):
        return False
    if not (-150.0 <= z <= 0.0 and -360.0 <= rz <= 360.0):
        return False
    return -165.0 <= math.degrees(math.atan2(y, x)) <= 165.0


def _seg_dist_origin(ax: float, ay: float, bx: float, by: float) -> float:
    """Расстояние от (0, 0) до отрезка AB на плоскости XY."""
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0.0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / len2))
    return math.hypot(ax + t * dx, ay + t * dy)


def _planar_to_base(frame: tuple, p: tuple) -> tuple:
    """Плоская СК (ox, oy, oz, theta°, L): точка СК -> база. RZ_base = rz + theta."""
    ox, oy, oz, theta, _ = frame
    c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    x, y, z, rz = p
    return ox + c * x - s * y, oy + s * x + c * y, oz + z, rz + theta


def _planar_from_base(frame: tuple, q: tuple) -> tuple:
    ox, oy, oz, theta, _ = frame
    c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    dx, dy = q[0] - ox, q[1] - oy
    return c * dx + s * dy, -s * dx + c * dy, q[2] - oz, q[3] - theta


def _xy(r: float, ang_deg: float) -> tuple[float, float]:
    a = math.radians(ang_deg)
    return r * math.cos(a), r * math.sin(a)


# --- Стратегии (чистые данные; объекты API строятся в теле теста) -----------------------------------------------
def _flt(lo: float, hi: float):
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


@st.composite
def _walk(draw, n: int):
    """n точек-целей (x, y, z, rz) в базе: каждая строго в зоне (r 110..590, угол ±160, z -140..-10,
    rz ±350); у соседних |угол| меняется не более чем на 20° — отрезок проходит не ближе 108.3 мм от оси."""
    ang = draw(_flt(-160, 160))
    out = []
    for _ in range(n):
        ang = max(-160.0, min(160.0, ang + draw(_flt(-20, 20))))
        x, y = _xy(draw(_flt(110, 590)), ang)
        out.append((x, y, draw(_flt(-140, -10)), draw(_flt(-350, 350))))
    return out


@st.composite
def _steps(draw, max_steps: int = 14):
    """Валидные по построению шаги: первый — Move, последний Move — не LINE_PASS. Элементы:
    ("move", kind, (x, y, z, rz)) или ("action", act, value)."""
    n = draw(st.integers(1, max_steps))
    shape = ["move"] + [draw(st.sampled_from(("move", "action"))) for _ in range(n - 1)]
    targets = draw(_walk(shape.count("move")))
    out = []
    mi = 0
    for tag in shape:
        if tag == "move":
            out.append(["move", draw(st.sampled_from(KINDS)), targets[mi]])
            mi += 1
        else:
            act = draw(st.sampled_from(sorted(ACTION_RANGES)))
            lo, hi = ACTION_RANGES[act]
            out.append(["action", act, draw(st.integers(lo, hi))])
    last_move = max(i for i, s in enumerate(out) if s[0] == "move")
    if out[last_move][1] == "LINE_PASS":
        out[last_move][1] = "LINE"
    return [tuple(s) for s in out]


def _materialize(api: SimpleNamespace, steps: list) -> tuple[list, dict]:
    """Шаги-данные -> объекты API и словарь точек (имя p<k> по индексу шага)."""
    objs, points = [], {}
    for k, (tag, a, b) in enumerate(steps):
        if tag == "move":
            name = f"p{k}"
            points[name] = _point(api, name, *b)
            objs.append(api.Move(point=name, kind=a))
        else:
            objs.append(api.Action(act=a, value=b))
    return objs, points


def _records_by_step(scenario) -> dict[int, list]:
    out: dict[int, list] = {}
    for rec, k in zip(scenario.records, scenario.step_of, strict=True):
        out.setdefault(k, []).append(rec)
    return out


# --- a. Круг «программа -> записи -> обратно» ----------------------------------------------------------------
@st.composite
def _roundtrip_case(draw):
    n = draw(st.integers(1, 6))
    targets = draw(_walk(n))
    kinds = [draw(st.sampled_from(KINDS)) for _ in range(n)]
    if kinds[-1] == "LINE_PASS":
        kinds[-1] = "LINE"
    frames = draw(
        st.lists(
            st.tuples(_flt(-300, 300), _flt(-300, 300), _flt(-100, 100), _flt(-179, 179), _flt(10, 500)),
            max_size=3,
        )
    )
    choice = [draw(st.integers(0, len(frames))) for _ in range(n)]  # 0 — база, i — СК номер i-1
    return targets, kinds, frames, choice


@_SETTINGS
@given(case=_roundtrip_case())
def test_roundtrip_planar_frames_within_005(case):
    """Программа из Move по точкам в плоских СК (и в базе) -> to_dict/from_dict -> записи совпадают с
    оракулом «СК -> база» (O + R(theta)·p, RZ = rz + theta), а обратный пересчёт даёт исходные x, y, z, rz
    в пределах ±0.05 по каждой координате.

    НЕ доказывает: наклонные СК (их держит свойство b), смешанные с действиями программы (h), поведение
    при вырожденной СК и точность хранения в регистрах (кодирование записей — вне T3.3)."""
    api = _api()
    targets, kinds, frames, choice = case
    frame_defs = {}
    for i, (ox, oy, oz, theta, length) in enumerate(frames):
        c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
        frame_defs[f"f{i}"] = api.FrameDef(
            name=f"f{i}",
            origin=(ox, oy, oz),
            on_x=(ox + length * c, oy + length * s, oz),
            in_plane=(ox - length * s, oy + length * c, oz),
        )
    points, steps, locals_, expected = {}, [], [], []
    for k, (base, kind, ci) in enumerate(zip(targets, kinds, choice, strict=True)):
        if ci == 0:
            local, frame_name, want = base, None, base
        else:
            frame_name = f"f{ci - 1}"
            lx, ly, lz, lrz = _planar_from_base(frames[ci - 1], base)
            lrz = max(-171.0, min(171.0, lrz))  # локальный rz в ±171: RZ в базе = rz + theta лежит в ±350
            local = (lx, ly, lz, lrz)
            want = _planar_to_base(frames[ci - 1], local)  # ожидаемое — оракулом «СК -> база», не из base
        points[f"p{k}"] = _point(api, f"p{k}", *local, frame=frame_name)
        steps.append(api.Move(point=f"p{k}", kind=kind))
        locals_.append(local)
        expected.append(want)
    scenario = _run(api, steps, points, frame_defs)
    scenario = api.Scenario.from_dict(scenario.to_dict())
    by_step = _records_by_step(scenario)
    assert len(scenario.records) == len(steps)
    for k, want in enumerate(expected):
        assert len(by_step.get(k, [])) == 1, f"шаг {k}: записей {len(by_step.get(k, []))}"
        rec = by_step[k][0]
        got = (rec.x, rec.y, rec.z, rec.rz)
        for name, g, w in zip(("x", "y", "z", "rz"), got, want, strict=True):
            assert abs(g - w) <= TOL, f"шаг {k}, {name} в базе: {g} против оракула {w}"
        back = _planar_from_base(frames[choice[k] - 1], got) if choice[k] else got
        for name, g, w in zip(("x", "y", "z", "rz"), back, locals_[k], strict=True):
            assert abs(g - w) <= TOL, f"шаг {k}, {name} обратно в СК: {g} против исходной {w}"


# --- b. СК -> база -> СК — тождество -------------------------------------------------------------------------
@st.composite
def _frame_and_point(draw):
    """Невырожденная СК, ось Z которой смотрит вверх (нормаль наклонена от вертикали не более чем на 60°),
    |on_x - origin| 10..400, расстояние от in_plane до прямой оси X 10..400; координаты в ±2000."""
    o = (draw(_flt(-1000, 1000)), draw(_flt(-1000, 1000)), draw(_flt(-1000, 1000)))
    alpha, beta, psi = (math.radians(draw(_flt(lo, hi))) for lo, hi in ((0, 60), (-180, 180), (-180, 180)))
    n = (math.sin(alpha) * math.cos(beta), math.sin(alpha) * math.sin(beta), math.cos(alpha))
    e1 = (math.cos(alpha) * math.cos(beta), math.cos(alpha) * math.sin(beta), -math.sin(alpha))
    e2 = (-math.sin(beta), math.cos(beta), 0.0)
    u = tuple(e1[i] * math.cos(psi) + e2[i] * math.sin(psi) for i in range(3))  # ось X СК
    v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])  # n x u — ось Y СК
    length, along, dist = draw(_flt(10, 400)), draw(_flt(-100, 100)), draw(_flt(10, 400))
    on_x = tuple(o[i] + length * u[i] for i in range(3))
    in_plane = tuple(o[i] + along * u[i] + dist * v[i] for i in range(3))
    p = (draw(_flt(-2000, 2000)), draw(_flt(-2000, 2000)), draw(_flt(-2000, 2000)), draw(_flt(-170, 170)))
    return o, on_x, in_plane, p


@_SETTINGS
@given(case=_frame_and_point())
def test_frame_to_base_from_base_identity(case):
    """from_base(to_base(p)) == p и to_base(from_base(q)) == q с допуском 1e-6 для случайной невырожденной
    (в том числе наклонной) СК и случайной точки.

    НЕ доказывает: что to_base даёт правильную точку в базе (это оракул свойства a для плоских СК —
    тождество выдержит и «неправильный», но взаимно обратный пересчёт), поведение на вырожденных СК и
    нормирование RZ по кругу (допущение A4: RZ не нормируется)."""
    api = _api()
    o, on_x, in_plane, p = case
    frame = api.FrameDef(name="t", origin=o, on_x=on_x, in_plane=in_plane)
    assert tuple(frame.from_base(*frame.to_base(*p))) == pytest.approx(p, abs=1e-6)
    assert tuple(frame.to_base(*frame.from_base(*p))) == pytest.approx(p, abs=1e-6)


# --- c, d, e. Зона точки -------------------------------------------------------------------------------------
_INT_POINT = st.tuples(
    st.sampled_from(("JOINT", "JOINT", "JOINT", "LINE", "LINE_PASS")),
    st.integers(-700, 700),
    st.integers(-700, 700),
    st.integers(-160, 10),
    st.integers(-380, 380),
)


@_SETTINGS
@example(pts=[("JOINT", 600, 0, 0, 360)])
@example(pts=[("JOINT", 100, 0, -150, -360)])
@example(pts=[("JOINT", 0, 600, -150, 360)])
@given(pts=st.lists(_INT_POINT, min_size=1, max_size=6))
def test_no_record_outside_zone(pts):
    """Точки из широкого бокса (целые мм, граница зоны достижима точно): если компиляция прошла — каждая
    запись в зоне по оракулу §7.3; если хоть одна точка программы вне зоны — CompileError; программа только
    из JOINT с точками в зоне (включая границы кольца, Z и RZ) обязана скомпилироваться.

    НЕ доказывает: причину отказа (код 4 держит e), отрезки (f, g), и что программа с LINE в зоне
    компилируется (может отказать по мёртвой зоне — это норма для этого свойства)."""
    api = _api()
    steps, points = [], {}
    for k, (kind, x, y, z, rz) in enumerate(pts):
        points[f"p{k}"] = _point(api, f"p{k}", x, y, z, rz)
        steps.append(api.Move(point=f"p{k}", kind=kind))
    all_in_zone = all(_in_zone(x, y, z, rz) for _, x, y, z, rz in pts)
    try:
        scenario = _run(api, steps, points)
    except api.CompileError:
        scenario = None
    if scenario is not None:
        for i, rec in enumerate(scenario.records):
            assert _in_zone(rec.x, rec.y, rec.z, rec.rz), f"запись {i} вне зоны: {(rec.x, rec.y, rec.z, rec.rz)}"
        assert all_in_zone, "компиляция прошла, а точка программы вне зоны"
    if all_in_zone and all(kind == "JOINT" for kind, *_ in pts):
        assert scenario is not None, "точки в зоне, ходы JOINT — отказа быть не должно"


@_SETTINGS
@given(targets=st.integers(1, 8).flatmap(_walk))
def test_in_zone_program_compiles(targets):
    """Пара к c: точки строго внутри зоны (r 110..590, угол ±160, z -140..-10), только JOINT — компиляция
    успешна, записей ровно столько, сколько Move.

    НЕ доказывает: отказ вне зоны (c, e), ходы LINE и действия (h), значения координат записей (a)."""
    api = _api()
    steps, points = [], {}
    for k, t in enumerate(targets):
        points[f"p{k}"] = _point(api, f"p{k}", *t)
        steps.append(api.Move(point=f"p{k}", kind="JOINT"))
    scenario = _run(api, steps, points)
    assert len(scenario.records) == len(targets)


@st.composite
def _bad_point(draw):
    """Точка заведомо вне зоны (запас от границы не менее 10 мм / 10°): один из шести признаков."""
    r, ang, z, rz = draw(_flt(110, 590)), draw(_flt(-160, 160)), draw(_flt(-140, -10)), draw(_flt(-350, 350))
    mode = draw(st.integers(0, 5))
    sign = draw(st.sampled_from((-1.0, 1.0)))
    if mode == 0:
        r = draw(_flt(0, 90))
    elif mode == 1:
        r = draw(_flt(610, 900))
    elif mode == 2:
        z = draw(_flt(10, 200))
    elif mode == 3:
        z = draw(_flt(-300, -160))
    elif mode == 4:
        rz = sign * draw(_flt(370, 600))
    else:
        ang = sign * draw(_flt(170, 180))
    x, y = _xy(r, ang)
    return x, y, z, rz


@st.composite
def _good_point(draw):
    return draw(_walk(1))[0]


@st.composite
def _first_offender_case(draw):
    prefix = draw(st.lists(_good_point(), max_size=5))
    bad = draw(_bad_point())
    suffix = draw(st.lists(st.one_of(_good_point(), _bad_point()), max_size=4))
    return prefix, bad, suffix


@_SETTINGS
@given(case=_first_offender_case())
def test_out_of_zone_rejected_at_first_offending_step(case):
    """Только JOINT, в программе одна или несколько точек вне зоны: CompileError с reason == 4 и step ==
    индексу первого Move с точкой вне зоны (точки до него — в зоне).

    НЕ доказывает: порядок проверок против других причин (5, 6, 7), отказ при неизвестной точке или СК,
    границу зоны (точки здесь заведомо дальше 10 мм/10° от границы; границу держит c)."""
    api = _api()
    prefix, bad, suffix = case
    pts = [*prefix, bad, *suffix]
    steps, points = [], {}
    for k, t in enumerate(pts):
        points[f"p{k}"] = _point(api, f"p{k}", *t)
        steps.append(api.Move(point=f"p{k}", kind="JOINT"))
    assert not _in_zone(*bad)  # оракул согласен с генератором
    with pytest.raises(api.CompileError) as info:
        _run(api, steps, points)
    assert info.value.reason == 4
    assert info.value.step == len(prefix)


# --- f, g. Отрезок LINE и мёртвая зона -----------------------------------------------------------------------
@st.composite
def _free_program(draw):
    n = draw(st.integers(2, 6))
    pts = []
    for _ in range(n):
        x, y = _xy(draw(_flt(110, 590)), draw(_flt(-160, 160)))
        kind = draw(st.sampled_from(("LINE", "LINE_PASS", "JOINT", "LINE")))
        pts.append((kind, x, y, draw(_flt(-140, -10)), draw(_flt(-350, 350))))
    if pts[-1][0] == "LINE_PASS":
        pts[-1] = ("LINE", *pts[-1][1:])
    return pts


@_SETTINGS
@example(
    pts=[
        ("JOINT", 200.0, 100.0, -50.0, 0.0),
        ("LINE_PASS", -50.0, -150.0, -50.0, 0.0),
        ("JOINT", -100.0, -300.0, -50.0, 0.0),
    ]
)
@given(pts=_free_program())
def test_no_line_segment_through_dead_zone(pts):
    """Точки в зоне, виды LINE / LINE_PASS / JOINT вперемешку: если компиляция прошла — для каждой пары
    соседних записей, где вторая LINE или LINE_PASS, расстояние от (0, 0) до XY-отрезка >= 100 по оракулу.
    Отказ CompileError — допустимый исход (свойство тогда пусто; непустоту держит g).

    НЕ доказывает: что нужные программы вообще компилируются (g, d), причину отказа, сектор углов вдоль
    отрезка и первый отрезок от текущей позы (его в компиляторе нет)."""
    api = _api()
    steps, points = [], {}
    for k, (kind, x, y, z, rz) in enumerate(pts):
        points[f"p{k}"] = _point(api, f"p{k}", x, y, z, rz)
        steps.append(api.Move(point=f"p{k}", kind=kind))
    try:
        scenario = _run(api, steps, points)
    except api.CompileError:
        return
    recs = scenario.records
    for i in range(1, len(recs)):
        if recs[i].kind in ("LINE", "LINE_PASS"):
            d = _seg_dist_origin(recs[i - 1].x, recs[i - 1].y, recs[i].x, recs[i].y)
            assert d >= 100.0 - 1e-9, f"отрезок {i - 1}->{i} ({recs[i].kind}) в {d:.3f} мм от оси J1"


def _two_moves(api: SimpleNamespace, a: tuple, b: tuple, kind: str):
    points = {"a": _point(api, "a", *a), "b": _point(api, "b", *b)}
    steps = [api.Move(point="a", kind="JOINT"), api.Move(point="b", kind=kind)]
    return _run(api, steps, points)


def test_dead_zone_line_rejected_joint_allowed():
    """Литералы: (200, 100, -50, 0) и (-50, -150, -50, 0) обе в зоне, прямая между ними проходит в 70.7 мм
    от оси: [JOINT, LINE] -> CompileError, reason == 5, step == 1; [JOINT, JOINT] -> успех, две записи.
    Граница 100 мм с обеих сторон: отрезок y = 99 отклоняется, отрезок y = 101 принимается.

    НЕ доказывает: LINE_PASS (его держит пример в f), сектор углов вдоль отрезка, радиальный ход через
    ось и точное равенство 100.000 мм."""
    api = _api()
    near, far = (200.0, 100.0, -50.0, 0.0), (-50.0, -150.0, -50.0, 0.0)
    with pytest.raises(api.CompileError) as info:
        _two_moves(api, near, far, "LINE")
    assert (info.value.reason, info.value.step) == (5, 1)
    assert len(_two_moves(api, near, far, "JOINT").records) == 2
    with pytest.raises(api.CompileError) as info99:
        _two_moves(api, (-300.0, 99.0, -50.0, 0.0), (300.0, 99.0, -50.0, 0.0), "LINE")
    assert (info99.value.reason, info99.value.step) == (5, 1)
    assert len(_two_moves(api, (-300.0, 101.0, -50.0, 0.0), (300.0, 101.0, -50.0, 0.0), "LINE").records) == 2


# --- h. Индекс-карта биективна по шагам движения --------------------------------------------------------------
@_SETTINGS
@given(steps=_steps())
def test_index_map_bijective_on_moves(steps):
    """Случайные программы из Move и Action (первый шаг — Move, последний Move — не LINE_PASS, точки
    валидны по построению): на каждый Move — ровно одна запись; step_of не убывает; Action после Move
    не-PASS сливается в его запись, иначе даёт запись LINE с теми же координатами; записи LINE_PASS без
    действия; ни одно действие не потеряно и порядок действий сохранён.

    НЕ доказывает: координаты записей (a), коды отказов, кодирование действий в регистры, поведение
    Action до первого Move (такой программы тест не строит)."""
    api = _api()
    objs, points = _materialize(api, steps)
    scenario = _run(api, objs, points)
    recs, step_of = scenario.records, list(scenario.step_of)
    assert len(step_of) == len(recs)
    assert step_of == sorted(step_of), "step_of убывает"
    by_step = _records_by_step(scenario)
    n_moves = sum(1 for s in steps if s[0] == "move")
    for k, (tag, a, b) in enumerate(steps):
        if tag == "move":
            assert len(by_step.get(k, [])) == 1, f"Move шага {k}: записей {len(by_step.get(k, []))}"
            assert by_step[k][0].kind == a
    extra = [r for k, r in zip(step_of, recs, strict=True) if steps[k][0] != "move"]
    assert all(r.kind == "LINE" and r.action != "NONE" for r in extra)
    assert len(recs) == n_moves + len(extra)
    assert [(r.action, r.aparam) for r in recs if r.action != "NONE"] == [
        (a, b) for tag, a, b in steps if tag == "action"
    ]
    assert all(r.action == "NONE" for r in recs if r.kind == "LINE_PASS")
    for k, (tag, act, value) in enumerate(steps):
        if tag != "action":
            continue
        prev_tag, prev_kind, _ = steps[k - 1]
        if prev_tag == "move" and prev_kind != "LINE_PASS":
            assert by_step.get(k, []) == [], f"Action шага {k} после Move не-PASS дал новую запись"
            merged = by_step[k - 1][0]
            assert (merged.action, merged.aparam) == (act, value)
        else:
            assert len(by_step.get(k, [])) == 1, f"Action шага {k} должен дать ровно одну запись"
            dup = by_step[k][0]
            before = [r for s, r in zip(step_of, recs, strict=True) if s < k][-1]
            assert dup.kind == "LINE" and (dup.action, dup.aparam) == (act, value)
            assert (dup.x, dup.y, dup.z, dup.rz) == (before.x, before.y, before.z, before.rz)


# --- i. Последняя запись — не LINE_PASS ----------------------------------------------------------------------
@_SETTINGS
@given(steps=_steps(), bad_last=st.booleans())
def test_last_record_never_pass(steps, bad_last):
    """Успешная ветка: любая скомпилированная программа (последний Move — не LINE_PASS) кончается записью
    не LINE_PASS. Ветка отказа: последний Move = LINE_PASS с 0, 1 и 2 действиями после него — CompileError,
    reason == 6, step == индекс этого Move; последний Move с точкой вне зоны даёт тоже 6 (проверка 6 раньше
    проверки точки, допущение A5).

    НЕ доказывает: LINE_PASS в середине программы допустим по другим причинам, порядок 6 против 7 и 5,
    поведение Action сразу после LINE_PASS (h)."""
    api = _api()
    objs, points = _materialize(api, steps)
    scenario = _run(api, objs, points)
    assert scenario.records[-1].kind != "LINE_PASS"
    last_move = max(k for k, s in enumerate(steps) if s[0] == "move")
    head = [list(s) for s in steps[: last_move + 1]]
    head[last_move][1] = "LINE_PASS"
    if bad_last:
        x, y = _xy(800.0, 0.0)
        head[last_move][2] = (x, y, -50.0, 0.0)  # r = 800 > 600
    for n_after in (0, 1, 2):
        tail = [("action", "DELAY_MS", 10 + j) for j in range(n_after)]
        objs, points = _materialize(api, [*[tuple(s) for s in head], *tail])
        with pytest.raises(api.CompileError) as info:
            _run(api, objs, points)
        assert info.value.reason == 6, f"{n_after} действий после LINE_PASS: reason {info.value.reason}"
        assert info.value.step == last_move
