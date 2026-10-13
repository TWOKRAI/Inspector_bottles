"""Слепая приёмка T3.4: генераторы программ робота (draw, circle_stroke, square_stroke, return_slot, toolchange).

Purpose: закрепить контракт пакета ``Services.robot_comm.programs.generators`` независимыми оракулами
до того, как пакет написан: снимок геометрии на фикстуре «Л+И» (14 записей литералами), «между штрихами нет
LINE_PASS», все Z из {перо вниз, перо вверх, подъём}, ряд LINE_PASS не длиннее 26, транзит инструмента через
«над 1» в обе стороны, ошибка «обучите точки», литерал маршрута return_slot, прохождение ``compile_program``
(первый ход JOINT, последний не LINE_PASS). Оракулы читают записи ``Scenario``, а не код генераторов.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite

Допущения (что тесты принимают на веру; чего НЕ доказывают):
  A1  API и имена — как в брифе T3.4.tester: ``GeneratedProgram`` — кортеж ``(program, points)``; точки
      ``draw`` лежат в СК ``frame`` (иначе снимок «Л+И» не сошёлся бы); ``GeneratorError`` — ``ValueError``.
      Тесты НЕ проверяют имена точек, которые генераторы придумывают сами (кроме ``home`` и библиотечных
      ``tN_over/pick/exit``).
  A2  Параметры зоны ``PARAMS`` и СК листа ``SHEET`` — литералы брифа; ``compile_program`` (T3.3) считаем
      верным. Тесты НЕ проверяют сам ``compile_program``.
  A3  Свойство c берёт z на сетке 0.5 мм (а не произвольные float): так ``pd``, ``pu``, ``pl`` разделены
      заведомо больше 1e-6 и сравнение «другой z» однозначно. Тесты НЕ доказывают поведение при ``lift_mm``
      порядка 1e-7 и при ``pen_up - pen_down`` порядка 1e-7.
  A4  ``accel``, ``max_pass_run`` не по умолчанию, ``name`` и ``slot`` в СК (``slot.frame != None``) в
      приёмку брифа не входят — НЕ проверяются.
  A5  Сообщение ``GeneratorError`` проверяется по подстрокам из брифа («обучите точки», «неизвестный номер
      инструмента») без учёта регистра; имена точек — с учётом регистра.
Импорт пакетов — в ``_api()`` внутри тела теста: до кода каждый тест краснеет отдельно, сборка файла цела.
Всё, что может зависнуть (генератор, компиляция), идёт через ``_guard``: поток-демон с дедлайном.
"""

from __future__ import annotations

import math
import threading
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, example, given, settings
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
TOL = 1e-6
DEADLINE_S = 30.0
HOME_ROW = (300.0, -210.0, -40.0, -100.0, "JOINT", "NONE", 0)

# Фикстура «Л+И» (СК листа, мм): «Л» одним штрихом; «И» двумя (правая черта начинается в конце диагонали).
LI = (
    ((0, 0), (8, 40), (25, 40), (25, 0)),
    ((35, 40), (35, 0), (55, 40)),
    ((55, 40), (55, 0)),
)
# Ожидаемые записи compile_program на «Л+И» (x, y, z, rz, kind, action, aparam) — литералы брифа, п.3.
LI_ROWS = [
    (300, -100, -95, 0, "JOINT", "SPEED_PCT", 30),
    (300, -100, -100, 0, "LINE", "NONE", 0),
    (308, -60, -100, 0, "LINE_PASS", "NONE", 0),
    (325, -60, -100, 0, "LINE_PASS", "NONE", 0),
    (325, -100, -100, 0, "LINE", "SPEED_PCT", 100),
    (325, -100, -95, 0, "LINE", "NONE", 0),
    (335, -60, -95, 0, "LINE", "SPEED_PCT", 30),
    (335, -60, -100, 0, "LINE", "NONE", 0),
    (335, -100, -100, 0, "LINE_PASS", "NONE", 0),
    (355, -60, -100, 0, "LINE", "SPEED_PCT", 100),
    (355, -60, -95, 0, "LINE", "SPEED_PCT", 30),
    (355, -60, -100, 0, "LINE", "NONE", 0),
    (355, -100, -100, 0, "LINE", "SPEED_PCT", 100),
    (355, -100, -85, 0, "LINE", "NONE", 0),
]

# Библиотека инструментов (база, hand=1, rz=0): (x, y, z) по имени.
LIB_XYZ = {
    "t1_over": (400, 100, -20),
    "t1_pick": (400, 100, -80),
    "t1_exit": (400, 160, -80),
    "t2_over": (400, -100, -20),
    "t2_pick": (400, -100, -80),
    "t2_exit": (400, -40, -80),
}
# Записи 1 -> 2 (литералы брифа, п.f).
TC_1_TO_2_ROWS = [
    (400, 160, -80, 0, "JOINT", "ACCUR", 1),
    (400, 100, -80, 0, "LINE", "DELAY_MS", 1000),
    (400, 100, -80, 0, "LINE", "ACCUR", 0),
    (400, 100, -20, 0, "LINE", "NONE", 0),
    (400, -100, -20, 0, "LINE", "ACCUR", 1),
    (400, -100, -80, 0, "LINE", "DELAY_MS", 1000),
    (400, -100, -80, 0, "LINE", "ACCUR", 0),
    (400, -40, -80, 0, "LINE", "NONE", 0),
]
# Имена Move по маршрутам (литералы брифа, п.f).
TC_ROUTES = {
    (1, 2): ["t1_exit", "t1_pick", "t1_over", "t2_over", "t2_pick", "t2_exit"],
    (2, 1): ["t2_exit", "t2_pick", "t2_over", "t1_over", "t1_pick", "t1_exit"],
    (0, 2): ["t1_over", "t2_over", "t2_pick", "t2_exit"],
    (2, 0): ["t2_exit", "t2_pick", "t2_over", "t1_over"],
    (0, 1): ["t1_over", "t1_pick", "t1_exit"],
    (1, 0): ["t1_exit", "t1_pick", "t1_over"],
}


# --- Доступ к пакетам (импорт только здесь) -------------------------------------------------------------------
def _api() -> SimpleNamespace:
    from Services.robot_comm.programs import (
        Action,
        CompileError,
        FrameDef,
        Move,
        Point,
        compile_program,
    )
    from Services.robot_comm.programs.generators import (
        GeneratedProgram,
        GeneratorError,
        circle_stroke,
        draw,
        return_slot,
        square_stroke,
        toolchange,
    )

    return SimpleNamespace(
        Action=Action,
        CompileError=CompileError,
        FrameDef=FrameDef,
        Move=Move,
        Point=Point,
        compile_program=compile_program,
        GeneratedProgram=GeneratedProgram,
        GeneratorError=GeneratorError,
        circle_stroke=circle_stroke,
        draw=draw,
        return_slot=return_slot,
        square_stroke=square_stroke,
        toolchange=toolchange,
    )


def _guard(fn, *args, **kwargs):
    """Вызов в потоке-демоне с дедлайном: зависание генератора/компиляции — падение теста, не зависший прогон."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # передаём в поток теста как есть (в т.ч. GeneratorError для pytest.raises)
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(DEADLINE_S)
    if t.is_alive():
        pytest.fail(f"вызов {getattr(fn, '__name__', fn)} не завершился за {DEADLINE_S} с")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _sheet(api: SimpleNamespace):
    return api.FrameDef(name="sheet", origin=(300, -100, -100), on_x=(400, -100, -100), in_plane=(300, 0, -100))


def _home(api: SimpleNamespace):
    return api.Point(name="home", x=300, y=-210, z=-40, rz=-100, hand=1)


def _lib(api: SimpleNamespace) -> dict:
    return {name: api.Point(name=name, x=x, y=y, z=z, rz=0, hand=1) for name, (x, y, z) in LIB_XYZ.items()}


def _draw_li(api: SimpleNamespace, **extra):
    return _guard(api.draw, LI, frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0, **extra)


def _rows(api: SimpleNamespace, gp, frames: dict | None = None) -> list[tuple]:
    """Компиляция генерата -> строки (x, y, z, rz, kind, action, aparam)."""
    scenario = _guard(api.compile_program, gp.program, gp.points, frames or {}, dict(PARAMS))
    return [(r.x, r.y, r.z, r.rz, r.kind, r.action, r.aparam) for r in scenario.records]


def _assert_rows(got: list[tuple], want: list[tuple]) -> None:
    """Строки равны литералам: числа с допуском 1e-6, kind/action/aparam точно."""
    assert len(got) == len(want), f"записей {len(got)}, ожидалось {len(want)}: {got}"
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        assert tuple(g[4:]) == tuple(w[4:]), f"запись {i}: вид/действие {g[4:]}, ожидалось {w[4:]}"
        assert tuple(g[:4]) == pytest.approx(tuple(float(v) for v in w[:4]), abs=TOL), f"запись {i}: координаты"


def _move_names(api: SimpleNamespace, gp) -> list[str]:
    return [s.point for s in gp.program.steps if isinstance(s, api.Move)]


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL


def _longest_pass_run(rows: list[tuple]) -> int:
    best = run = 0
    for row in rows:
        run = run + 1 if row[4] == "LINE_PASS" else 0
        best = max(best, run)
    return best


def _count_lowerings(rows: list[tuple], pu: float, pd: float) -> int:
    """(в) пары соседних записей z: pu -> pd."""
    return sum(1 for a, b in zip(rows, rows[1:], strict=False) if _close(a[2], pu) and _close(b[2], pd))


def _assert_pen_properties(rows: list[tuple], *, pd: float, pu: float, pl: float, strokes: int) -> None:
    """Определения п.4 брифа: (а), (б), (в) и «действия только после EXACT». Оракул — только записи."""
    assert rows, "ни одной записи"
    for i, row in enumerate(rows):
        if row[4] == "LINE_PASS":
            assert _close(row[2], pd), f"(а) запись {i}: LINE_PASS на z={row[2]}, перо вниз {pd}"
    for i, (a, b) in enumerate(zip(rows, rows[1:], strict=False)):
        if not _close(a[2], b[2]):
            assert a[4] != "LINE_PASS", f"(б) запись {i}: LINE_PASS перед сменой z {a[2]} -> {b[2]}"
        if a[4] == "LINE_PASS":
            same = _close(a[0], b[0]) and _close(a[1], b[1]) and _close(a[2], b[2])
            assert not same, f"запись {i}: действие после LINE_PASS (следующая запись в тех же x, y, z)"
    assert _count_lowerings(rows, pu, pd) == strokes, (
        f"(в) опусканий {_count_lowerings(rows, pu, pd)}, штрихов {strokes}"
    )
    for i, row in enumerate(rows):
        assert any(_close(row[2], v) for v in (pd, pu, pl)), f"запись {i}: z={row[2]} вне {{pd, pu, pl}}"


# --- a ------------------------------------------------------------------------------------------------------
def test_li_snapshot() -> None:
    """Снимок геометрии «Л+И»: ровно 14 записей брифа (подвод JOINT, скорости, опускания, транзит пропущен, подъём).

    НЕ доказывает: поведение на других рисунках (это свойство c), имена точек, число ``Move`` в программе,
    ``accel``.
    """
    api = _api()
    gp = _draw_li(api)
    _assert_rows(_rows(api, gp, {"sheet": _sheet(api)}), LI_ROWS)


# --- b ------------------------------------------------------------------------------------------------------
def test_li_no_pass_between_strokes() -> None:
    """«Л+И»: нет LINE_PASS между штрихами (а)-(в) п.4, три опускания, множество z == {-100, -95, -85}.

    НЕ доказывает: то же для произвольных рисунков (свойство c); сами значения x, y (снимок a).
    """
    api = _api()
    rows = _rows(api, _draw_li(api), {"sheet": _sheet(api)})
    _assert_pen_properties(rows, pd=-100.0, pu=-95.0, pl=-85.0, strokes=3)
    assert _count_lowerings(rows, -95.0, -100.0) == 3  # якорь существования: опускания есть, не «пусто»
    assert {round(r[2], 6) for r in rows} == {-100.0, -95.0, -85.0}


# --- c ------------------------------------------------------------------------------------------------------
_COORD = st.integers(0, 120).map(lambda v: v / 2)  # сетка 0.5 мм в [0, 60]: точные повторы есть, почти-повторов нет
_POINT = st.tuples(_COORD, _COORD)
# Штрих 1..60 точек; половина — длинные (28..60): иначе hypothesis почти не доходит до границы 26 LINE_PASS.
_STROKE = st.one_of(
    st.lists(_POINT, min_size=1, max_size=60),
    st.lists(_POINT, min_size=28, max_size=60),
)
_PD = st.integers(-40, 0).map(lambda v: v / 2)  # pen_down в [-20, 0]
_D = st.integers(2, 40).map(lambda v: v / 2)  # pen_up - pen_down в [1, 20]
_LIFT = st.integers(0, 60).map(lambda v: v / 2)  # lift_mm в [0, 30]


@settings(max_examples=100, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.too_slow])
@example(strokes=[[(10.0, 10.0), (10.0, 10.0), (20.0, 10.0)]], pd=-5.0, d=5.0, lift=10.0)  # повтор в начале штриха
@example(strokes=[[(10.0, 10.0), (20.0, 10.0), (20.0, 10.0), (30.0, 10.0)]], pd=-5.0, d=5.0, lift=0.0)  # повтор внутри
@example(strokes=[[(5.0, 5.0), (5.0, 5.0)], [(5.0, 5.0)], [(6.0, 5.0)]], pd=0.0, d=1.0, lift=30.0)  # штрихи-«точки»
@example(strokes=[[(0.5 * (j % 100), float(j % 7)) for j in range(60)]], pd=-20.0, d=20.0, lift=0.0)  # длинный штрих
@given(strokes=st.lists(_STROKE, min_size=1, max_size=5), pd=_PD, d=_D, lift=_LIFT)
def test_random_strokes_properties(strokes, pd, d, lift) -> None:
    """Случайные рисунки: компиляция успешна; z только {pd, pu, pl}; (а)-(в); действия после EXACT; ряд <= 26;
    первая запись JOINT, последняя LINE; соседних записей пера в одной XY нет (повторы отброшены).

    НЕ доказывает: рисунки вне сетки 0.5 мм и со штрихами длиннее 60 точек; точные координаты (снимок a);
    скорости пера/переезда; что генератор не ИЗМЕНИЛ порядок точек штриха (оракул смотрит на структуру).
    """
    api = _api()
    pu = pd + d
    gp = _guard(api.draw, strokes, frame="sheet", hand=1, rz=0.0, pen_down=pd, pen_up=pu, lift_mm=lift)
    rows = _rows(api, gp, {"sheet": _sheet(api)})  # CompileError здесь = падение: без assume и перехвата
    bpd, bpu, bpl = -100.0 + pd, -100.0 + pu, -100.0 + pu + lift
    _assert_pen_properties(rows, pd=bpd, pu=bpu, pl=bpl, strokes=len(strokes))
    assert _longest_pass_run(rows) <= 26
    assert rows[0][4] == "JOINT"
    assert rows[-1][4] == "LINE"
    for i, (a, b) in enumerate(zip(rows, rows[1:], strict=False)):
        if _close(a[2], bpd) and _close(b[2], bpd):
            same_xy = _close(a[0], b[0]) and _close(a[1], b[1])
            assert not same_xy, f"запись {i}: ход нулевой длины внутри штриха"


# --- d ------------------------------------------------------------------------------------------------------
def test_long_stroke_and_circle_exact_every_26() -> None:
    """Штрих из 100 точек и круг из 64 сегментов: EXACT (LINE) вставлен каждые 26 LINE_PASS.

    Штрих: на высоте пера 100 записей, 95 LINE_PASS, 5 LINE, самый длинный ряд ровно 26. Круг: 65 записей,
    61 LINE_PASS, 4 LINE, ряд <= 26.
    НЕ доказывает: координаты точек круга (тест e); ``max_pass_run`` не по умолчанию.
    """
    api = _api()
    frames = {"sheet": _sheet(api)}
    line = tuple((0.5 * j, 20.0) for j in range(100))
    rows = _rows(api, _guard(api.draw, (line,), frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0), frames)
    pen = [r for r in rows if _close(r[2], -100.0)]
    assert len(pen) == 100
    assert sum(1 for r in pen if r[4] == "LINE_PASS") == 95
    assert sum(1 for r in pen if r[4] == "LINE") == 5
    assert _longest_pass_run(rows) == 26

    circle = _guard(api.circle_stroke, 30, 20, 15)
    rows = _rows(api, _guard(api.draw, (circle,), frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0), frames)
    pen = [r for r in rows if _close(r[2], -100.0)]
    assert len(pen) == 65
    assert sum(1 for r in pen if r[4] == "LINE_PASS") == 61
    assert sum(1 for r in pen if r[4] == "LINE") == 4
    assert _longest_pass_run(rows) <= 26


# --- e ------------------------------------------------------------------------------------------------------
def test_circle_and_square_strokes() -> None:
    """``circle_stroke`` / ``square_stroke``: точки, замыкание, обход против часовой, ошибки аргументов.

    НЕ доказывает: годность штрихов для ``draw`` (тест d), поведение при ``segments`` от 3 до 7 и при
    отрицательном радиусе.
    """
    api = _api()
    pts = api.circle_stroke(30, 20, 15, segments=8)
    assert len(pts) == 9
    assert pts[0] == pytest.approx((45.0, 20.0), abs=1e-9)
    assert pts[-1] == pts[0]
    assert pts[2] == pytest.approx((30.0, 35.0), abs=1e-9)
    for i, (x, y) in enumerate(pts):
        assert math.hypot(x - 30.0, y - 20.0) == pytest.approx(15.0, abs=1e-9), f"точка {i} не на окружности"
    assert pts[1][1] > 20.0  # вторая точка выше центра: обход против часовой
    assert len(api.circle_stroke(0, 0, 10)) == 65
    assert api.square_stroke(0, 0, 20, 10) == ((0, 0), (20, 0), (20, 10), (0, 10), (0, 0))
    with pytest.raises(api.GeneratorError):
        api.circle_stroke(0, 0, 0)
    with pytest.raises(api.GeneratorError):
        api.circle_stroke(0, 0, 10, segments=2)
    with pytest.raises(api.GeneratorError):
        api.square_stroke(0, 0, 0, 10)


# --- f ------------------------------------------------------------------------------------------------------
def test_toolchange_via_over_1_both_ways() -> None:
    """Смена инструмента через «над 1» в обе стороны: имена ходов шести маршрутов, JOINT первым и LINE дальше,
    литералы записей 1 -> 2, ``approach=HOME`` добавляет подвод JOINT и весь маршрут LINE.

    НЕ доказывает: ``home`` (тест i); обработку отсутствующих точек (тест g); маршруты с ``seat_delay_ms`` не по
    умолчанию; тела маршрутов 2 -> 1, 0 -> 2 и др. на уровне записей (проверены только имена ходов и компиляция).
    """
    api = _api()
    lib = _lib(api)
    for (cur, tgt), names in TC_ROUTES.items():
        gp = _guard(api.toolchange, cur, tgt, lib)
        moves = [s for s in gp.program.steps if isinstance(s, api.Move)]
        assert [m.point for m in moves] == names, f"маршрут {cur}->{tgt}"
        assert moves[0].kind == "JOINT", f"маршрут {cur}->{tgt}: первый ход"
        assert all(m.kind == "LINE" for m in moves[1:]), f"маршрут {cur}->{tgt}: остальные LINE"
        assert _rows(api, gp)  # компиляция успешна, записи есть
    _assert_rows(_rows(api, _guard(api.toolchange, 1, 2, lib)), TC_1_TO_2_ROWS)
    with_approach = _rows(api, _guard(api.toolchange, 1, 2, lib, approach=_home(api)))
    assert len(with_approach) == 9
    _assert_rows(with_approach[:1], [HOME_ROW])
    _assert_rows(with_approach[1:2], [(400, 160, -80, 0, "LINE", "ACCUR", 1)])
    _assert_rows(with_approach[2:], TC_1_TO_2_ROWS[1:])


# --- g ------------------------------------------------------------------------------------------------------
def test_toolchange_missing_points_says_teach() -> None:
    """Нехватка точек: ошибка «обучите точки» называет ВСЕ недостающие и только их; неизвестный и совпадающий номера.

    НЕ доказывает: порядок имён в тексте; формулировку кроме подстрок брифа; что при полной библиотеке ошибки нет
    (это тест f).
    """
    api = _api()
    lib = _lib(api)
    partial = {k: v for k, v in lib.items() if k not in ("t2_pick", "t1_exit")}
    with pytest.raises(api.GeneratorError) as info:
        _guard(api.toolchange, 1, 2, partial)
    text = str(info.value)
    assert "обучите точки" in text.lower()
    assert "t1_exit" in text
    assert "t2_pick" in text
    assert "t1_over" not in text

    only_tool_1 = {k: v for k, v in lib.items() if k.startswith("t1_")}
    gp = _guard(api.toolchange, 0, 1, only_tool_1)  # точки инструмента 2 не нужны
    assert _move_names(api, gp) == ["t1_over", "t1_pick", "t1_exit"]

    with pytest.raises(api.GeneratorError):
        _guard(api.toolchange, 1, 1, lib)
    with pytest.raises(api.GeneratorError) as info:
        _guard(api.toolchange, 3, 1, lib)
    assert "неизвестный номер инструмента" in str(info.value).lower()


# --- h ------------------------------------------------------------------------------------------------------
def test_return_slot_literal() -> None:
    """``return_slot`` на слоте (350, -150, -90, rz 10): семь записей брифа (над, захват DO_ON+DELAY, подъём,
    сдвиг на 100 мм, опускание, DO_OFF+DELAY).

    НЕ доказывает: ``approach``/``home`` (тест i); ``lift_mm``, ``push_dx_mm``/``push_dy_mm``, ``grip_do``,
    ``grip_delay_ms`` не по умолчанию; слот в СК.
    """
    api = _api()
    slot = api.Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
    gp = _guard(api.return_slot, slot)
    _assert_rows(
        _rows(api, gp),
        [
            (350, -150, -70, 10, "JOINT", "NONE", 0),
            (350, -150, -90, 10, "LINE", "DO_ON", 1),
            (350, -150, -90, 10, "LINE", "DELAY_MS", 400),
            (350, -150, -70, 10, "LINE", "NONE", 0),
            (450, -150, -70, 10, "LINE", "NONE", 0),
            (450, -150, -90, 10, "LINE", "DO_OFF", 1),
            (450, -150, -90, 10, "LINE", "DELAY_MS", 400),
        ],
    )


# --- i ------------------------------------------------------------------------------------------------------
def test_generated_programs_respect_compile_rules() -> None:
    """Программы всех трёх генераторов, без ``home`` и с ``home=HOME``: первый шаг — Move JOINT, до первого Move
    нет Action, последний Move не LINE_PASS, компиляция успешна; с ``home`` последняя запись — JOINT в HOME и
    ``"home"`` в ``points``; ``approach=HOME`` у return_slot/toolchange даёт первой записью HOME JOINT, второй LINE.

    НЕ доказывает: координаты маршрутов (тесты a, f, h); ``approach`` у ``draw`` (его в API нет); что
    ``approach`` и ``home`` с одним именем но разными координатами не склеиваются.
    """
    api = _api()
    home = _home(api)
    lib = _lib(api)
    slot = api.Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
    frames = {"sheet": _sheet(api)}
    cases = {
        "draw": (lambda **kw: api.draw(LI, frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0, **kw), frames),
        "return_slot": (lambda **kw: api.return_slot(slot, **kw), {}),
        "toolchange": (lambda **kw: api.toolchange(1, 2, lib, **kw), {}),
    }
    for label, (make, fr) in cases.items():
        for with_home in (False, True):
            gp = _guard(make, **({"home": home} if with_home else {}))
            program, points = gp  # GeneratedProgram — кортеж (program, points)
            assert program is gp.program and points is gp.points
            steps = program.steps
            assert isinstance(steps[0], api.Move) and steps[0].kind == "JOINT", f"{label}: первый шаг"
            moves = [s for s in steps if isinstance(s, api.Move)]
            assert moves[-1].kind != "LINE_PASS", f"{label}: последний Move"
            rows = _rows(api, gp, fr)
            if with_home:
                _assert_rows(rows[-1:], [HOME_ROW])
                assert "home" in points, f"{label}: home не в points"
    for label, make in (
        ("return_slot", lambda **kw: api.return_slot(slot, **kw)),
        ("toolchange", lambda **kw: api.toolchange(1, 2, lib, **kw)),
    ):
        rows = _rows(api, _guard(make, approach=home))
        _assert_rows(rows[:1], [HOME_ROW])
        assert rows[1][4] == "LINE", f"{label}: вторая запись после approach"


# --- j ------------------------------------------------------------------------------------------------------
def test_draw_rejects_bad_arguments() -> None:
    """Плохие аргументы ``draw``: пустой рисунок, пустой штрих, ``pen_up`` не выше ``pen_down`` -> GeneratorError;
    ``draw_speed_pct=0`` -> ValueError; GeneratorError — подкласс ValueError.

    НЕ доказывает: отказ на нечисловых координатах, на отрицательном ``lift_mm``, на ``travel_speed_pct=0``.
    """
    api = _api()
    assert issubclass(api.GeneratorError, ValueError)
    kw = {"frame": "sheet", "hand": 1, "rz": 0.0, "pen_down": 0.0, "pen_up": 5.0}
    with pytest.raises(api.GeneratorError):
        _guard(api.draw, (), **kw)
    with pytest.raises(api.GeneratorError):
        _guard(api.draw, ((),), **kw)
    with pytest.raises(api.GeneratorError):
        _guard(api.draw, LI, **{**kw, "pen_up": 0.0})
    with pytest.raises(ValueError):
        _guard(api.draw, LI, **kw, draw_speed_pct=0)
