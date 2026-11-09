"""Слепые приёмочные тесты T5.4, часть 2: команды калибровки хаба против sim v2 (B1-B9).

Purpose:
    Закрепить по файлу приёмки (критерии B1-B9) команды ``robot_calib_belt`` / ``robot_calib_frame`` /
    ``robot_calib_tools`` плагина ``device_hub``: плагин -> настоящий драйвер ``RobotDriverV2`` -> sim v2 (``E2eRig``).
    Вход тестера - только файл приёмки и публичные заглушки пакета калибровки.

Как устроено:
    * Плагин собирается на ``make_ctx`` (conftest); подключение - ``cmd_device_connect`` + разбор очереди
      ``_process_conn_queue`` (шов образцов хаба: фейковый ``WorkerManager`` рабочий поток не запускает; настоящий
      ``WorkerManager`` супервизор не запустил - подключение не наступало). Приватных имён ДРАЙВЕРА в файле нет;
      ``_do_configure`` / ``_do_start`` - в одном тесте каталога (B9): иначе команды не попадают в ``CommandManager``.
    * Робот читается публично: параметр - ``rig.client.param_get`` (свой клиент стенда на тот же sim), признак «есть
      неприменённые параметры» - регистр sim ``TLM_CFG_PENDING``, записи в робота - строки событий sim
      ``op=PARAM_SET`` / ``op=PARAM_APPLY``.
    * Команда зовётся как ``plugin.cmd_<имя>``; пока её нет, тест падает осмысленным ``AssertionError``
      («команда не зарегистрирована»), а не ``AttributeError`` в чужой строке.
    * Блокирующие вызовы и ожидания идут под дедлайном (daemon-поток + join в ``bounded``, опрос с дедлайном).
    * Ожидаемые значения - литералы приёмки (14451, 1384, тексты отказов); входы вычислены в тесте из литералов.

Public API:
    Только тесты ``test_b<N>_*``.

Stability: lite
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

_CALL_S = 20.0
_CONNECT_S = 60.0
_DEV = "r1"

TEXT_BAD_ARGS = "неверные аргументы команды робота"
TEXT_SHORT = "мало хода ленты между отметками"
TEXT_OFF_AXIS = "лента не вдоль оси робота"
TEXT_NO_ENCODER = "энкодер не изменился между отметками"
TEXT_NO_POINT = "точка не найдена"
TEXT_IN_BASE = "точка СК должна быть в базе"

_BELT_COMMANDS = ("robot_calib_belt", "robot_calib_frame", "robot_calib_tools")
_DEFAULT_FACTOR = 14447  # умолчание P_BELT_FACTOR (таблица параметров)
_DEFAULT_DIR = 1  # умолчание P_BELT_DIR

_C30 = 0.8660254037844386  # cos 30
_S30 = 0.5  # sin 30


# --------------------------------------------------------------------------------------------------
# Обвязка
# --------------------------------------------------------------------------------------------------


class _Hub:
    """Плагин ``device_hub`` над настоящим ``DeviceManager`` + (опционально) робот стенда; только публичные швы."""

    def __init__(self, plugin: DeviceHubPlugin, ctx: Any, base: Path, rig: E2eRig | None) -> None:
        self.plugin = plugin
        self.ctx = ctx
        self.base = base
        self.rig = rig

    # --- команды ---------------------------------------------------------------------------

    def cmd(self, name: str, data: dict | None = None) -> dict:
        """Команда ``cmd_<имя>`` под дедлайном; ``device_id`` подставляется. Нет команды - ``AssertionError``."""
        fn = getattr(self.plugin, f"cmd_{name}", None)
        assert fn is not None, f"команда {name} не зарегистрирована в плагине (нет cmd_{name})"
        payload = {"device_id": _DEV, **(data or {})}
        return bounded(lambda: fn(dict(payload)), _CALL_S)

    def params_rev(self) -> str | None:
        res = self.cmd("robot_param_get_all")
        assert res["status"] == "ok", res
        return res["rev"]

    def points_rev(self) -> str | None:
        res = self.cmd("robot_point_list")
        assert res["status"] == "ok", res
        return res["rev"]

    def frames(self) -> dict:
        res = self.cmd("robot_frame_list")
        assert res["status"] == "ok", res
        return res

    def save_point(self, name: str, x: float, y: float, z: float, *, frame: str | None = None) -> None:
        point: dict[str, Any] = {"name": name, "x": x, "y": y, "z": z, "rz": 0.0, "hand": 1}
        if frame is not None:
            point["frame"] = frame
        res = self.cmd("robot_point_save", {"point": point, "base_rev": self.points_rev()})
        assert res["status"] == "ok", res

    # --- робот -----------------------------------------------------------------------------

    def param(self, name: str) -> int:
        assert self.rig is not None
        return bounded(lambda: self.rig.client.param_get(name), _CALL_S)

    def pending(self) -> int:
        assert self.rig is not None
        return self.rig.core.regs[REG["TLM_CFG_PENDING"]]

    def mark(self) -> int:
        assert self.rig is not None
        return len(self.rig.core.events())

    def sim_texts(self, since: int) -> list[str]:
        assert self.rig is not None
        return [text for _stamp, text in self.rig.core.events()[since:]]

    def robot_belt(self) -> tuple[int, int]:
        return self.param("P_BELT_FACTOR"), self.param("P_BELT_DIR")

    def params_file(self) -> Path:
        return self.base / "robot" / _DEV / "params.yaml"

    # --- подключение -----------------------------------------------------------------------

    def connect(self) -> None:
        """Подключение: команда ставит в очередь, разбор очереди - вызовом (как в образцах хаба)."""
        assert self.plugin.cmd_device_connect({"device_id": _DEV})["status"] == "ok"
        bounded(self.plugin._process_conn_queue, _CONNECT_S)
        path = f"devices.state.{_DEV}.conn"
        conns = [c.args[1] for c in self.ctx.state_proxy.set.call_args_list if c.args[0] == path]
        assert conns and conns[-1] == {"conn": "connected"}, f"робот не подключился: {conns[-3:]}"


def _entry(port: int) -> dict:
    return {
        "id": _DEV,
        "name": _DEV,
        "kind": "robot",
        "protocol": "delta_v2",
        "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        "params": {},
    }


@contextmanager
def _make_hub(base: Path, monkeypatch: pytest.MonkeyPatch, *, online: bool) -> Iterator[_Hub]:
    """Плагин в каталоге ``base``; ``online`` - sim v2 + подключённый ``r1``."""
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
    base.mkdir(parents=True, exist_ok=True)
    registry = base / "devices.yaml"
    config = {"registry_path": str(registry), "supervisor_interval_s": 0.05}
    ctx = make_ctx(config, tmp_registry=registry)
    plugin = DeviceHubPlugin()
    rig_cm = E2eRig() if online else None
    rig = rig_cm.__enter__() if rig_cm is not None else None
    try:
        plugin.configure(ctx)
        plugin.start(ctx)
        hub = _Hub(plugin, ctx, base, rig)
        port = rig.port if rig is not None else 50999
        assert hub.plugin.cmd_device_upsert(_entry(port))["status"] == "ok"
        if online:
            hub.connect()
        yield hub
    finally:
        try:
            bounded(lambda: plugin.shutdown(ctx), 15.0)
        except Exception:  # noqa: BLE001 - уборка не подменяет провал теста
            pass
        if rig_cm is not None:
            rig_cm.__exit__(None, None, None)


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Hub]:
    with _make_hub(tmp_path, monkeypatch, online=True) as h:
        yield h


@pytest.fixture
def offline_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Hub]:
    with _make_hub(tmp_path, monkeypatch, online=False) as h:
        yield h


def _mark(x: float, y: float, enc: Any) -> dict:
    return {"x_mm": x, "y_mm": y, "encoder": enc}


# B1: 200 мм по +Y, энкодер 1000 -> 2384 (1384 имп): 200/1384 = 0.14450867 -> сырое 14451
_MARKS_PLUS_Y = [_mark(250, -100, 1000), _mark(250, 100, 2384)]
_RAW_PLUS_Y = 14451
# Ход 200 мм по +Y за 1200 имп: 0.16666 -> 16667 (другое значение для устаревшей ревизии)
_MARKS_OTHER = [_mark(250, -100, 1000), _mark(250, 100, 2200)]


def _calibrate(hub: _Hub, marks: list[dict] | None = None, **extra: Any) -> dict:
    """``robot_calib_belt`` со свежей ``base_rev`` (из ``robot_param_get_all``)."""
    args: dict[str, Any] = {"marks": marks if marks is not None else _MARKS_PLUS_Y, "base_rev": hub.params_rev()}
    args.update(extra)
    return hub.cmd("robot_calib_belt", args)


# --------------------------------------------------------------------------------------------------
# B1-B3 - лента: запись, направление, сухой прогон
# --------------------------------------------------------------------------------------------------


def test_b1_belt_reply_fields(hub: _Hub) -> None:
    """B1: отметки (250,-100,1000) и (250,100,2384), свежая ``base_rev`` -> ``ok``, ``applied is True``, поля ответа."""
    res = _calibrate(hub)
    assert res["status"] == "ok", res
    assert res["applied"] is True
    assert res["raw_factor"] == _RAW_PLUS_Y
    assert res["factor_mm_per_imp"] == pytest.approx(0.1445087, abs=1e-6)
    assert res["direction"] == 1
    assert res["delta_enc"] == 1384
    assert res["travel_mm"] == pytest.approx(200.0, abs=1e-6)
    assert res["axis_dev_deg"] == pytest.approx(0.0, abs=1e-6)
    assert "P_BELT_FACTOR" in res["written"]
    assert isinstance(res["rev"], str) and res["rev"]


def test_b1_belt_values_land_on_robot_and_in_file(hub: _Hub) -> None:
    """B1: ``P_BELT_FACTOR`` (робот, ``robot_param_get_all``) == 14451; ``P_BELT_DIR`` == 1; PENDING == 0."""
    mark = hub.mark()
    res = _calibrate(hub)
    assert res["status"] == "ok", res
    assert hub.param("P_BELT_FACTOR") == _RAW_PLUS_Y
    assert hub.param("P_BELT_DIR") == 1
    in_file = hub.cmd("robot_param_get_all")
    assert in_file["params"]["P_BELT_FACTOR"]["raw"] == _RAW_PLUS_Y
    assert in_file["params"]["P_BELT_DIR"]["raw"] == 1
    assert hub.pending() == 0
    texts = hub.sim_texts(mark)
    assert any("op=PARAM_SET" in t for t in texts), "запись в робота не дошла до sim"
    assert any("op=PARAM_APPLY" in t for t in texts), "параметры класса reinit не применены"


def test_b2_minus_x_gives_direction_2_and_writes_both_params(hub: _Hub) -> None:
    """B2: ход по -X (энкодер растёт) -> ``P_BELT_DIR`` на роботе == 2, в ``written`` оба параметра."""
    marks = [_mark(500, 0, 1000), _mark(300, 0, 2384)]
    res = _calibrate(hub, marks)
    assert res["status"] == "ok", res
    assert res["direction"] == 2
    assert set(res["written"]) == {"P_BELT_FACTOR", "P_BELT_DIR"}
    assert hub.param("P_BELT_DIR") == 2
    assert hub.param("P_BELT_FACTOR") == _RAW_PLUS_Y


def test_b3_dry_run_reports_result_without_applying(hub: _Hub) -> None:
    """B3: ``dry_run: true`` -> ``ok``, ``applied is False``, расчёт в ответе, ревизии (``rev``) в ответе нет."""
    res = _calibrate(hub, dry_run=True)
    assert res["status"] == "ok", res
    assert res["applied"] is False
    assert res["raw_factor"] == _RAW_PLUS_Y
    assert res["direction"] == 1
    assert res.get("rev") is None


def test_b3_dry_run_leaves_robot_and_params_file_untouched(hub: _Hub) -> None:
    """B3: после ``dry_run`` параметры робота, ревизия файла параметров и поток записей в робота не изменились."""
    rev_before = hub.params_rev()
    robot_before = hub.robot_belt()
    assert robot_before == (_DEFAULT_FACTOR, _DEFAULT_DIR)
    file_existed = hub.params_file().exists()
    mark = hub.mark()
    res = hub.cmd("robot_calib_belt", {"marks": _MARKS_PLUS_Y, "base_rev": rev_before, "dry_run": True})
    assert res["status"] == "ok", res
    assert hub.robot_belt() == robot_before
    assert hub.params_rev() == rev_before
    assert hub.params_file().exists() == file_existed
    assert [t for t in hub.sim_texts(mark) if "op=PARAM_SET" in t] == []


# --------------------------------------------------------------------------------------------------
# B4-B6 - отказы ленты
# --------------------------------------------------------------------------------------------------

_BAD_ARGS = {
    "нет marks": {"base_rev": None},
    "одна отметка": {"marks": [_mark(250, -100, 1000)], "base_rev": None},
    "encoder дробный": {"marks": [_mark(250, -100, 1000.5), _mark(250, 100, 2384)], "base_rev": None},
    "encoder 2**31 вне 32 бит со знаком": {"marks": [_mark(250, -100, 1000), _mark(250, 100, 2**31)], "base_rev": None},
    "x_mm - true": {"marks": [_mark(True, -100, 1000), _mark(250, 100, 2384)], "base_rev": None},
    "dry_run - строка": {"marks": _MARKS_PLUS_Y, "base_rev": None, "dry_run": "true"},
}


@pytest.mark.parametrize("what", list(_BAD_ARGS))
def test_b4_bad_arguments_refused_and_robot_untouched(hub: _Hub, what: str) -> None:
    """B4: плохие аргументы -> «неверные аргументы команды робота»; параметры робота и поток записей не изменились."""
    before = hub.robot_belt()
    mark = hub.mark()
    res = hub.cmd("robot_calib_belt", _BAD_ARGS[what])
    assert res["status"] == "error", f"{what}: {res}"
    assert res["message"] == TEXT_BAD_ARGS, f"{what}: {res}"
    assert hub.robot_belt() == before
    assert [t for t in hub.sim_texts(mark) if "op=PARAM_SET" in t] == []


def test_b4_control_same_arguments_without_defect_are_accepted(hub: _Hub) -> None:
    """Контроль B4: те же аргументы без дефекта (``dry_run: true``) принимаются - отказы вызваны именно дефектом."""
    res = hub.cmd("robot_calib_belt", {"marks": _MARKS_PLUS_Y, "base_rev": None, "dry_run": True})
    assert res["status"] == "ok", res


_B5_CASES = {
    "ход 10 мм": ([_mark(250, -5, 1000), _mark(250, 5, 1070)], TEXT_SHORT),
    "угол 5 градусов": (
        [
            _mark(250, -100, 1000),
            _mark(250 + 200 * math.sin(math.radians(5)), -100 + 200 * math.cos(math.radians(5)), 2384),
        ],
        TEXT_OFF_AXIS,
    ),
    "энкодер равен": ([_mark(250, -100, 1000), _mark(250, 100, 1000)], TEXT_NO_ENCODER),
}


@pytest.mark.parametrize("what", list(_B5_CASES))
def test_b5_belt_math_refusals_pass_through_and_robot_untouched(hub: _Hub, what: str) -> None:
    """B5: ход 10 мм / угол 5 градусов / равный энкодер -> тексты A5 и A4; параметры робота не изменились."""
    marks, text = _B5_CASES[what]
    before = hub.robot_belt()
    mark = hub.mark()
    res = hub.cmd("robot_calib_belt", {"marks": marks, "base_rev": hub.params_rev()})
    assert res["status"] == "error", f"{what}: {res}"
    assert res["message"] == text, f"{what}: {res}"
    assert hub.robot_belt() == before
    assert [t for t in hub.sim_texts(mark) if "op=PARAM_SET" in t] == []


def test_b6_stale_base_rev_refused_with_current_rev(hub: _Hub) -> None:
    """B6: устаревшая ``base_rev`` (файл уже создан первой калибровкой) -> отказ с ``current_rev``; робот цел."""
    first = _calibrate(hub)
    assert first["status"] == "ok", first
    rev1 = first["rev"]
    before = hub.robot_belt()
    assert before == (_RAW_PLUS_Y, 1)
    mark = hub.mark()
    stale = hub.cmd("robot_calib_belt", {"marks": _MARKS_OTHER, "base_rev": None})
    assert stale["status"] == "error", stale
    assert stale["current_rev"] == rev1
    assert hub.robot_belt() == before
    assert [t for t in hub.sim_texts(mark) if "op=PARAM_SET" in t] == []


def test_b6_stale_base_rev_refused_even_when_nothing_to_write(hub: _Hub) -> None:
    """B6: те же отметки (писать нечего) + устаревшая ``base_rev`` -> отказ с ``current_rev``."""
    first = _calibrate(hub)
    assert first["status"] == "ok", first
    rev1 = first["rev"]
    again = hub.cmd("robot_calib_belt", {"marks": _MARKS_PLUS_Y, "base_rev": None})
    assert again["status"] == "error", again
    assert again["current_rev"] == rev1


# --------------------------------------------------------------------------------------------------
# B7 - СК по сохранённым точкам
# --------------------------------------------------------------------------------------------------


def _sheet_points(origin: tuple[float, float, float], prefix: str) -> list[tuple[str, float, float, float]]:
    """Углы листа A4 (0,0,0), (297,0,0), (0,210,0) при повороте 30 градусов вокруг Z и сдвиге ``origin`` (база, мм)."""
    ox, oy, oz = origin
    return [
        (f"{prefix}0", round(ox, 6), round(oy, 6), oz),
        (f"{prefix}1", round(ox + 297 * _C30, 6), round(oy + 297 * _S30, 6), oz),
        (f"{prefix}2", round(ox - 210 * _S30, 6), round(oy + 210 * _C30, 6), oz),
    ]


_LOCALS = [[0.0, 0.0, 0.0], [297.0, 0.0, 0.0], [0.0, 210.0, 0.0]]


def _save_sheet(hub: _Hub, origin: tuple[float, float, float], prefix: str) -> list[str]:
    pts = _sheet_points(origin, prefix)
    for name, x, y, z in pts:
        hub.save_point(name, x, y, z)
    return [p[0] for p in pts]


def _frame_args(hub: _Hub, name: str, names: list[str]) -> dict:
    return {
        "name": name,
        "points": [{"point": n, "local": loc} for n, loc in zip(names, _LOCALS, strict=True)],
        "base_rev": hub.frames()["rev"],
    }


def test_b7_frame_from_three_saved_points_reports_fit(hub: _Hub) -> None:
    """B7: СК по трём сохранённым точкам с номиналом листа -> ``ok``; yaw ~ 30, невязки малы, ``rev``, ``frame``."""
    names = _save_sheet(hub, (300.0, -100.0, -40.0), "s")
    res = hub.cmd("robot_calib_frame", _frame_args(hub, "sheet", names))
    assert res["status"] == "ok", res
    assert res["yaw_deg"] == pytest.approx(30.0, abs=0.01)
    assert len(res["residuals_mm"]) == 3
    assert res["max_residual_mm"] < 0.01
    assert isinstance(res["rev"], str) and res["rev"]
    assert "frame" in res


def test_b7_frame_is_listed_with_fitted_origin(hub: _Hub) -> None:
    """B7: ``robot_frame_list`` содержит СК с этим именем, начало = база-образ локального (0,0,0)."""
    names = _save_sheet(hub, (300.0, -100.0, -40.0), "s")
    assert hub.cmd("robot_calib_frame", _frame_args(hub, "sheet", names))["status"] == "ok"
    sheets = [f for f in hub.frames()["frames"] if f["name"] == "sheet"]
    assert len(sheets) == 1, sheets
    assert sheets[0]["origin"] == pytest.approx([300.0, -100.0, -40.0], abs=1e-3)


def test_b7_repeat_with_same_name_replaces_frame(hub: _Hub) -> None:
    """B7: повтор с тем же именем заменяет СК: одна запись ``sheet``, начало - от новых точек."""
    first = _save_sheet(hub, (300.0, -100.0, -40.0), "s")
    assert hub.cmd("robot_calib_frame", _frame_args(hub, "sheet", first))["status"] == "ok"
    second = _save_sheet(hub, (350.0, -50.0, -30.0), "u")
    res = hub.cmd("robot_calib_frame", _frame_args(hub, "sheet", second))
    assert res["status"] == "ok", res
    sheets = [f for f in hub.frames()["frames"] if f["name"] == "sheet"]
    assert len(sheets) == 1, sheets
    assert sheets[0]["origin"] == pytest.approx([350.0, -50.0, -30.0], abs=1e-3)


def test_b7_missing_point_refused(hub: _Hub) -> None:
    """B7: несуществующая точка -> «точка не найдена»; СК не появилась."""
    names = _save_sheet(hub, (300.0, -100.0, -40.0), "s")
    names[1] = "no_such_point"
    res = hub.cmd("robot_calib_frame", _frame_args(hub, "sheet", names))
    assert res["status"] == "error", res
    assert res["message"] == TEXT_NO_POINT
    assert [f for f in hub.frames()["frames"] if f["name"] == "sheet"] == []


def test_b7_point_in_foreign_frame_refused(hub: _Hub) -> None:
    """B7: точка в чужой СК -> «точка СК должна быть в базе»."""
    names = _save_sheet(hub, (300.0, -100.0, -40.0), "s")
    assert hub.cmd("robot_calib_frame", _frame_args(hub, "sheet", names))["status"] == "ok"
    hub.save_point("in_sheet", 10.0, 10.0, 0.0, frame="sheet")
    others = _save_sheet(hub, (350.0, -50.0, -30.0), "u")
    others[2] = "in_sheet"
    res = hub.cmd("robot_calib_frame", _frame_args(hub, "second", others))
    assert res["status"] == "error", res
    assert res["message"] == TEXT_IN_BASE


# --------------------------------------------------------------------------------------------------
# B8 - отчёт по инструментам
# --------------------------------------------------------------------------------------------------


def _save_tools(hub: _Hub, skip: tuple[str, ...] = ()) -> None:
    layout = {
        "t1_over": -30.0,
        "t1_pick": -60.0,
        "t1_exit": -30.0,
        "t2_over": -30.0,
        "t2_pick": -60.0,
        "t2_exit": -30.0,
    }
    for name, z in layout.items():
        if name not in skip:
            hub.save_point(name, 300.0, -100.0, z)


def test_b8_tools_report_full_set_both_ok(hub: _Hub) -> None:
    """B8: все точки инструментов 1 и 2 сохранены -> отчёт по обоим, оба ok, пропусков и проблем нет."""
    _save_tools(hub)
    res = hub.cmd("robot_calib_tools")
    assert res["status"] == "ok", res
    tools = {t["tool"]: t for t in res["tools"]}
    assert sorted(tools) == [1, 2]
    for n in (1, 2):
        assert tools[n]["ok"] is True, tools[n]
        assert list(tools[n]["missing"]) == []
        assert list(tools[n]["problems"]) == []


def test_b8_tools_report_names_missing_point(hub: _Hub) -> None:
    """B8: нет ``t2_exit`` -> у инструмента 2 ``missing == ["t2_exit"]``, не ok; инструмент 1 ok."""
    _save_tools(hub, skip=("t2_exit",))
    res = hub.cmd("robot_calib_tools")
    assert res["status"] == "ok", res
    tools = {t["tool"]: t for t in res["tools"]}
    assert list(tools[2]["missing"]) == ["t2_exit"]
    assert tools[2]["ok"] is False
    assert tools[1]["ok"] is True


def test_b8_tools_report_does_not_change_points_revision(hub: _Hub) -> None:
    """B8: ревизия ``robot_point_list`` до и после ``robot_calib_tools`` равна (команда читает, не пишет)."""
    _save_tools(hub)
    before = hub.points_rev()
    assert before is not None
    res = hub.cmd("robot_calib_tools")
    assert res["status"] == "ok", res
    assert hub.points_rev() == before


# --------------------------------------------------------------------------------------------------
# B9 - каталог и работа без связи
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", _BELT_COMMANDS)
def test_b9_command_is_in_plugin_commands(name: str) -> None:
    """B9: команда есть в таблице ``DeviceHubPlugin.commands``."""
    assert name in DeviceHubPlugin.commands, f"{name} нет в DeviceHubPlugin.commands"


def test_b9_commands_have_nonempty_catalog_description(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B9: у трёх команд непустое описание в каталоге: ``get_command_info(name)`` -> ``metadata.description``."""
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
    registry = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry)}, tmp_registry=registry)
    manager = CommandManager("devices")
    assert manager.initialize()
    ctx.command_manager = manager
    plugin = DeviceHubPlugin()
    bounded(lambda: plugin._do_configure(ctx), _CALL_S)
    bounded(lambda: plugin._do_start(ctx), _CALL_S)
    try:
        for name in _BELT_COMMANDS:
            info = manager.get_command_info(name)
            assert info is not None, f"{name}: нет в каталоге"
            description = (info.get("metadata") or {}).get("description")
            assert isinstance(description, str) and description.strip(), f"{name}: описание пусто ({description!r})"
    finally:
        bounded(lambda: plugin.shutdown(ctx), 15.0)


def test_b9_frame_and_tools_answer_without_robot_link(offline_hub: _Hub) -> None:
    """B9: ``robot_calib_frame`` и ``robot_calib_tools`` отвечают ``ok`` без связи с роботом (данные - из файлов)."""
    names = _save_sheet(offline_hub, (300.0, -100.0, -40.0), "s")
    frame = offline_hub.cmd("robot_calib_frame", _frame_args(offline_hub, "sheet", names))
    assert frame["status"] == "ok", frame
    tools = offline_hub.cmd("robot_calib_tools")
    assert tools["status"] == "ok", tools
    assert sorted(t["tool"] for t in tools["tools"]) == [1, 2]


@pytest.mark.parametrize("dry_run", [False, True], ids=["write", "dry_run"])
def test_b9_belt_without_robot_link_is_refused_and_file_untouched(offline_hub: _Hub, dry_run: bool) -> None:
    """B9: ``robot_calib_belt`` без связи - отказ (и с ``dry_run: true``); файл параметров не создан и не изменён."""
    rev_before = offline_hub.params_rev()
    existed = offline_hub.params_file().exists()
    args: dict[str, Any] = {"marks": _MARKS_PLUS_Y, "base_rev": rev_before}
    if dry_run:
        args["dry_run"] = True
    res = offline_hub.cmd("robot_calib_belt", args)
    assert res["status"] == "error", res
    assert isinstance(res["message"], str) and res["message"]
    assert offline_hub.params_rev() == rev_before
    assert offline_hub.params_file().exists() == existed
