"""Слепая приёмка T5.3c, часть c1: команды данных робота v2, каталог, Д2, старые имена.

Purpose:
    Контракт части c1 (``plans/robot-protocol-v2/tasks/T5.3c.md``, DESIGN 1-7, REDS 1-9 и 12): офлайн-команды данных
    (программы, точки, СК, параметры) идут через ``DeviceManager.robot_data`` мимо ``call``;
    ``write_registers`` отказывает для ``delta_v2`` (Д2) до проверки связи;
    21 новое имя несёт описание в каталоге; старые имена работают как прежде.
    Плагин собирается на ``make_ctx`` + настоящий ``CommandManager``; реестр - ровно ``tmp_path / "devices.yaml"``
    (корень данных плагина - ``tmp_path / "robot"``); ``INSPECTOR_DATA_DIR`` снят.

Public API:
    Только тесты ``test_*``.

Stability: lite

Правила файла: ожидаемые значения - литералы брифа (ни одно не считается кодом под тестом); вызов, который может
повиснуть, идёт через ``bounded`` (daemon-поток с дедлайном); имена, которых на базе нет, берутся внутри тела теста
(``getattr`` на плагине), а не при сборе модуля.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

_CALL_S = 20.0
_CONNECT_S = 60.0

TEXT_STALE = "Данные робота изменены с момента чтения"
TEXT_BAD_ARGS = "неверные аргументы команды робота"
TEXT_BAD_KEY = "Недопустимое имя данных робота"
TEXT_ONLY_V2 = "данные робота — только для протокола delta_v2"
TEXT_NO_POINT = "точка не найдена"
TEXT_FRAME_DEGENERATE = "точки СК вырождены"
TEXT_FRAME_IN_BASE = "точка СК должна быть в базе"
TEXT_D2 = "запись регистров робота v2 — только командами robot_*"
DESC_PREFIX = "Робот v2: "

_STEP = {"op": "move", "point": "a", "kind": "JOINT"}
_PROGRAM_P1 = {"name": "p1", "steps": [_STEP]}
_PROGRAM_P1_STORED = {"version": 1, "name": "p1", "steps": [{"op": "move", "point": "a", "kind": "JOINT"}]}

# 21 новое имя: DESIGN 5 (10 офлайн + 11 через call)
_NEW_NAMES = (
    "robot_param_get_all",
    "robot_point_list",
    "robot_point_save",
    "robot_point_delete",
    "robot_frame_list",
    "robot_frame_teach",
    "robot_program_list",
    "robot_program_get",
    "robot_program_save",
    "robot_program_delete",
    "robot_param_set",
    "robot_param_apply",
    "robot_stop",
    "robot_servo",
    "robot_do_set",
    "robot_jog_step",
    "robot_jog_hold",
    "robot_jog_release",
    "robot_point_capture",
    "robot_program_run",
    "robot_program_abort",
)

# 27 прежних имён v1 (14 робота без журнала + 2 журнала считаются отдельно + 11 рисования; О2: без изменений)
_OLD_NAMES = (
    "robot_enqueue_job",
    "robot_return_job",
    "robot_send_test_job",
    "robot_abort",
    "robot_set_mode",
    "robot_jog",
    "robot_jog_abort",
    "robot_set_servo",
    "robot_set_robot_config",
    "robot_get_robot_config",
    "robot_get_telemetry",
    "robot_read_echo",
    "robot_set_manual_mode",
    "robot_clear_queue",
    "robot_set_encoder_offset",
    "robot_toolchange",
    "robot_draw_polyline",
    "robot_draw_circle",
    "robot_draw_square",
    "robot_draw_set_pen",
    "robot_draw_set_speed",
    "robot_draw_set_travel",
    "robot_draw_set_accel",
    "robot_draw_set_pass_size",
    "robot_draw_set_overlap",
    "robot_draw_abort",
    "robot_draw_progress",
)
_LOG_NAMES = ("robot_exchange_log_get", "robot_exchange_log_set")


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


def _transport(port: int) -> dict:
    return {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": 2}


def _v2_entry(dev_id: str = "r1", port: int = 50999) -> dict:
    return {"id": dev_id, "name": dev_id, "kind": "robot", "protocol": "delta_v2", "transport": _transport(port)}


def _plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, real_commands: bool = False
) -> tuple[DeviceHubPlugin, Any]:
    """Плагин на ``make_ctx``; реестр - ровно ``tmp_path / "devices.yaml"``; ``INSPECTOR_DATA_DIR`` снят.

    ``real_commands`` - настоящий ``CommandManager`` в ``ctx.command_manager`` и путь ``_do_configure`` / ``_do_start``
    (как у фреймворка: команды регистрируются после ``configure``, описания пишет ``start``).
    """
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
    registry = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry)}, tmp_registry=registry)
    plugin = DeviceHubPlugin()
    if real_commands:
        manager = CommandManager("devices")
        assert manager.initialize()
        ctx.command_manager = manager
        plugin._do_configure(ctx)
        plugin._do_start(ctx)
    else:
        plugin.configure(ctx)
        plugin.start(ctx)
    return plugin, ctx


def _cmd(plugin: DeviceHubPlugin, name: str, data: dict) -> dict:
    """Команда плагина по имени ``robot_*`` / ``device_*`` (``cmd_<имя>``) под дедлайном; копия аргументов."""

    def call() -> dict:
        return getattr(plugin, f"cmd_{name}")(dict(data))

    return bounded(call, _CALL_S)


def _add_v2(plugin: DeviceHubPlugin, dev_id: str = "r1", port: int = 50999) -> None:
    assert _cmd(plugin, "device_upsert", _v2_entry(dev_id, port))["status"] == "ok"


def _point(name: str, x: float, y: float, z: float, *, frame: str | None = None) -> dict:
    point = {"name": name, "x": x, "y": y, "z": z, "rz": 0.0, "hand": 1}
    if frame is not None:
        point["frame"] = frame
    return point


def _save_point(plugin: DeviceHubPlugin, point: dict) -> dict:
    """``point_save`` с ``base_rev`` из ``point_list`` (как велит бриф: точки сохраняются с актуальной ревизией)."""
    rev = _cmd(plugin, "robot_point_list", {"device_id": "r1"})["rev"]
    res = _cmd(plugin, "robot_point_save", {"device_id": "r1", "point": point, "base_rev": rev})
    assert res["status"] == "ok", res
    return res


def _program_file(tmp_path: Path, name: str = "p1") -> Path:
    return tmp_path / "robot" / "r1" / "programs" / f"{name}.yaml"


def _shutdown(plugin: DeviceHubPlugin, ctx: Any) -> None:
    bounded(lambda: plugin.shutdown(ctx), 10.0)


# --------------------------------------------------------------------------------------------------
# REDS 1-9, 12
# --------------------------------------------------------------------------------------------------


def test_program_save_list_get_delete_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 1: цикл программы без связи с роботом; файл на диске; ``program_get`` отдаёт тело с ``version``."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)

    saved = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": _PROGRAM_P1, "base_rev": None})
    assert saved["status"] == "ok", saved
    assert isinstance(saved["rev"], str) and saved["rev"]
    assert _program_file(tmp_path).is_file()

    listed = _cmd(plugin, "robot_program_list", {"device_id": "r1"})
    assert listed["status"] == "ok", listed
    assert listed["programs"] == ["p1"]

    got = _cmd(plugin, "robot_program_get", {"device_id": "r1", "name": "p1"})
    assert got["status"] == "ok", got
    assert got["program"] == _PROGRAM_P1_STORED
    assert got["rev"] == saved["rev"]

    deleted = _cmd(plugin, "robot_program_delete", {"device_id": "r1", "name": "p1", "base_rev": saved["rev"]})
    assert deleted["status"] == "ok", deleted
    assert not _program_file(tmp_path).exists()
    assert _cmd(plugin, "robot_program_list", {"device_id": "r1"})["programs"] == []


def test_stale_rev_refused_with_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 2: устаревшая ``base_rev`` - отказ с постоянным текстом и ``current_rev`` на диске; файл не тронут."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)
    first = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": _PROGRAM_P1, "base_rev": None})
    assert first["status"] == "ok", first
    rev1 = first["rev"]
    before = _program_file(tmp_path).read_bytes()

    # второй save со старой ревизией (None: клиент считает, что файла ещё нет)
    stale = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": _PROGRAM_P1, "base_rev": None})
    assert stale["status"] == "error"
    assert stale["message"] == TEXT_STALE
    assert stale["current_rev"] == rev1
    assert _program_file(tmp_path).read_bytes() == before

    # настоящий сценарий устаревания: ревизия rev1 была актуальна, потом файл сменили
    longer = {"name": "p1", "steps": [_STEP, {"op": "move", "point": "b", "kind": "JOINT"}]}
    second = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": longer, "base_rev": rev1})
    assert second["status"] == "ok", second
    rev2 = second["rev"]
    assert rev2 != rev1
    after_second = _program_file(tmp_path).read_bytes()

    stale2 = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": _PROGRAM_P1, "base_rev": rev1})
    assert stale2["status"] == "error"
    assert stale2["message"] == TEXT_STALE
    assert stale2["current_rev"] == rev2
    assert _program_file(tmp_path).read_bytes() == after_second


def test_points_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 3: точка сохраняется и читается без связи; удаление несуществующей - «точка не найдена»."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)
    point_a = {"name": "a", "x": 300.0, "y": -210.0, "z": -40.0, "rz": -100.0, "hand": 1}

    saved = _cmd(plugin, "robot_point_save", {"device_id": "r1", "point": point_a, "base_rev": None})
    assert saved["status"] == "ok", saved
    assert isinstance(saved["rev"], str) and saved["rev"]

    listed = _cmd(plugin, "robot_point_list", {"device_id": "r1"})
    assert listed["status"] == "ok", listed
    assert [p["name"] for p in listed["points"]] == ["a"]
    got = listed["points"][0]
    assert (got["x"], got["y"], got["z"], got["rz"], got["hand"]) == (300.0, -210.0, -40.0, -100.0, 1)
    assert got.get("frame") is None
    assert listed["rev"] == saved["rev"]

    missing = _cmd(plugin, "robot_point_delete", {"device_id": "r1", "name": "zz", "base_rev": listed["rev"]})
    assert missing["status"] == "error"
    assert missing["message"] == TEXT_NO_POINT
    after = _cmd(plugin, "robot_point_list", {"device_id": "r1"})
    assert [p["name"] for p in after["points"]] == ["a"]
    assert after["rev"] == listed["rev"]


def test_frame_teach_from_three_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 4: СК из трёх сохранённых точек; вырожденные и точка не из базы - постоянные тексты отказа."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)
    for point in (
        _point("o", 0.0, 0.0, 0.0),
        _point("x", 100.0, 0.0, 0.0),
        _point("p", 0.0, 100.0, 0.0),
        _point("l0", 0.0, 0.0, 0.0),
        _point("l1", 100.0, 0.0, 0.0),
        _point("l2", 200.0, 0.0, 0.0),
    ):
        _save_point(plugin, point)

    taught = _cmd(
        plugin,
        "robot_frame_teach",
        {"device_id": "r1", "name": "sheet", "origin": "o", "on_x": "x", "in_plane": "p", "base_rev": None},
    )
    assert taught["status"] == "ok", taught
    listed = _cmd(plugin, "robot_frame_list", {"device_id": "r1"})
    assert listed["status"] == "ok", listed
    sheets = [f for f in listed["frames"] if f["name"] == "sheet"]
    assert len(sheets) == 1, listed["frames"]
    assert sheets[0]["origin"] == [0.0, 0.0, 0.0]
    assert sheets[0]["on_x"] == [100.0, 0.0, 0.0]
    assert sheets[0]["in_plane"] == [0.0, 100.0, 0.0]

    degenerate = _cmd(
        plugin,
        "robot_frame_teach",
        {"device_id": "r1", "name": "bad", "origin": "l0", "on_x": "l1", "in_plane": "l2", "base_rev": listed["rev"]},
    )
    assert degenerate["status"] == "error"
    assert degenerate["message"] == TEXT_FRAME_DEGENERATE

    _save_point(plugin, _point("fp", 0.0, 50.0, 0.0, frame="sheet"))
    in_frame = _cmd(
        plugin,
        "robot_frame_teach",
        {"device_id": "r1", "name": "t2", "origin": "o", "on_x": "x", "in_plane": "fp", "base_rev": listed["rev"]},
    )
    assert in_frame["status"] == "error"
    assert in_frame["message"] == TEXT_FRAME_IN_BASE

    after = _cmd(plugin, "robot_frame_list", {"device_id": "r1"})
    assert [f["name"] for f in after["frames"]] == ["sheet"]
    assert after["rev"] == listed["rev"]


def test_param_get_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 5: без файла - умолчания, ``epoch == 1``, ``rev is None``; после записи ``params.yaml`` - значения файла."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)

    fresh = _cmd(plugin, "robot_param_get_all", {"device_id": "r1"})
    assert fresh["status"] == "ok", fresh
    assert fresh["params"]["P_SPD_DEFAULT"] == {"raw": 80, "value": 80.0}
    assert fresh["epoch"] == 1
    assert fresh["rev"] is None

    written_rev = RobotDataStore(tmp_path / "robot").write(
        "r1", "params", {"version": 1, "epoch": 4, "values": {"P_SPD_DEFAULT": 55}}, base_rev=None
    )
    from_file = _cmd(plugin, "robot_param_get_all", {"device_id": "r1"})
    assert from_file["status"] == "ok", from_file
    assert from_file["params"]["P_SPD_DEFAULT"] == {"raw": 55, "value": 55.0}
    assert from_file["epoch"] == 4
    assert from_file["rev"] == written_rev


def test_refusals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 6: недопустимое имя программы, устройство не v2, неизвестное устройство - отказ без исключения."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)
    v1 = {
        "id": "v1",
        "name": "v1",
        "kind": "robot",
        "protocol": "delta_universal3",
        "transport": _transport(50998),
    }
    assert _cmd(plugin, "device_upsert", v1)["status"] == "ok"

    bad_save = _cmd(
        plugin,
        "robot_program_save",
        {"device_id": "r1", "program": {"name": "../x", "steps": [_STEP]}, "base_rev": None},
    )
    assert bad_save["status"] == "error"
    assert bad_save["message"] == TEXT_BAD_KEY
    bad_get = _cmd(plugin, "robot_program_get", {"device_id": "r1", "name": "../x"})
    assert bad_get["status"] == "error"
    assert bad_get["message"] == TEXT_BAD_KEY
    assert not (tmp_path / "robot" / "r1" / "x.yaml").exists()
    assert not (tmp_path / "robot" / "x.yaml").exists()

    on_v1 = _cmd(plugin, "robot_program_list", {"device_id": "v1"})
    assert on_v1["status"] == "error"
    assert on_v1["message"] == TEXT_ONLY_V2
    on_v1_write = _cmd(
        plugin, "robot_point_save", {"device_id": "v1", "point": _point("a", 1.0, 2.0, 3.0), "base_rev": None}
    )
    assert on_v1_write["status"] == "error"
    assert on_v1_write["message"] == TEXT_ONLY_V2
    assert not (tmp_path / "robot" / "v1").exists()

    unknown = _cmd(plugin, "robot_point_list", {"device_id": "nope"})
    assert unknown["status"] == "error"
    assert isinstance(unknown["message"], str) and unknown["message"]


def test_v2_generic_write_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 7 (Д2): ``device_write`` в служебный регистр v2 отказывает литералом - и без связи, и при связи."""
    plugin, ctx = _plugin(tmp_path, monkeypatch)
    with E2eRig() as rig:
        try:
            _add_v2(plugin, "r1", rig.port)

            # не подключён: отказ Д2 не зависит от связи (иначе «Устройство 'r1' не подключено»)
            offline = _cmd(plugin, "device_write", {"device_id": "r1", "values": {"HB_PC": 5}})
            assert offline["status"] == "error"
            assert offline["message"] == TEXT_D2

            assert _cmd(plugin, "device_connect", {"device_id": "r1"})["status"] == "ok"
            bounded(plugin._process_conn_queue, _CONNECT_S)
            assert plugin._manager.get_driver("r1").is_connected

            online = _cmd(plugin, "device_write", {"device_id": "r1", "values": {"HB_PC": 5}})
            assert online["status"] == "error"
            assert online["message"] == TEXT_D2
            assert rig.read("HB_PC") != [5]
        finally:
            _shutdown(plugin, ctx)


def test_catalogue_descriptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 8: 21 новое имя в каталоге несёт описание «Робот v2: ...» с ключами аргументов; 27 + 2 прежних - на месте."""
    plugin, ctx = _plugin(tmp_path, monkeypatch, real_commands=True)
    manager = ctx.command_manager
    try:
        missing = [n for n in _NEW_NAMES if manager.get_command_info(n) is None]
        assert missing == [], f"не зарегистрированы: {missing}"
        for name in _NEW_NAMES:
            description = (manager.get_command_info(name) or {}).get("metadata", {}).get("description", "")
            assert isinstance(description, str) and description.startswith(DESC_PREFIX), (name, description)
            assert "device_id" in description, (name, description)

        for name in _OLD_NAMES + _LOG_NAMES:
            assert name in DeviceHubPlugin.commands, name
            assert manager.get_command_info(name) is not None, name
        assert len(DeviceHubPlugin.commands) == 73
        assert len(_NEW_NAMES) == 21 and len(_OLD_NAMES) == 27 and len(set(_NEW_NAMES + _OLD_NAMES)) == 48
    finally:
        _shutdown(plugin, ctx)
        manager.shutdown()


def test_old_names_work_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_transport: Any, robot_entry: Any
) -> None:
    """RED 9 (FREEZE, О2): v2: ``enqueue_job`` работает, ``draw_polyline`` - «неизвестная операция»; v1 - как прежде."""
    from Services.device_hub.drivers.robot_driver import RobotDriver

    plugin, ctx = _plugin(tmp_path / "v2", monkeypatch)
    with E2eRig() as rig:
        try:
            _add_v2(plugin, "r1", rig.port)
            assert _cmd(plugin, "device_connect", {"device_id": "r1"})["status"] == "ok"
            bounded(plugin._process_conn_queue, _CONNECT_S)
            assert plugin._manager.get_driver("r1").is_connected

            queued = _cmd(plugin, "robot_enqueue_job", {"device_id": "r1", "x_mm": 300, "y_mm": -150})
            assert queued["status"] == "ok", queued
            assert queued["queue_len"] == 1

            draw = _cmd(
                plugin, "robot_draw_polyline", {"device_id": "r1", "points": [{"x_mm": 0, "y_mm": 0, "pen": 1}]}
            )
            assert draw["status"] == "error"
            assert draw["message"] == "Неизвестная операция робота: 'draw_polyline'"
        finally:
            _shutdown(plugin, ctx)

    # v1: драйвер на фейк-транспорте conftest; ответ - как на ``main`` (Services/device_hub/tests/test_robot_driver.py)
    plugin1, ctx1 = _plugin(tmp_path / "v1", monkeypatch)
    try:
        plugin1._manager.register_driver_factory(
            "robot", lambda entry, proto: RobotDriver(entry, proto, transport=fake_transport)
        )
        assert _cmd(plugin1, "device_upsert", robot_entry.to_dict())["status"] == "ok"
        assert plugin1._manager.connect(robot_entry.id) is True
        polyline = _cmd(
            plugin1,
            "robot_draw_polyline",
            {"device_id": robot_entry.id, "points": [{"x_mm": 0, "y_mm": 0, "pen": 1}]},
        )
        assert polyline["status"] == "ok", polyline
    finally:
        _shutdown(plugin1, ctx1)


def test_program_save_without_base_rev_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 12 (О6): запись без ключа ``base_rev`` - постоянный ``TEXT_BAD_ARGS``; ничего не записано."""
    plugin, _ctx = _plugin(tmp_path, monkeypatch)
    _add_v2(plugin)

    refused = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": _PROGRAM_P1})
    assert refused["status"] == "error"
    assert refused["message"] == TEXT_BAD_ARGS
    assert not _program_file(tmp_path).exists()

    # те же правила у остальных команд записи (DESIGN 4): точка и программа уже лежат, без base_rev ничего не меняется
    _save_point(plugin, _point("o", 0.0, 0.0, 0.0))
    _save_point(plugin, _point("x", 100.0, 0.0, 0.0))
    _save_point(plugin, _point("p", 0.0, 100.0, 0.0))
    saved = _cmd(plugin, "robot_program_save", {"device_id": "r1", "program": _PROGRAM_P1, "base_rev": None})
    assert saved["status"] == "ok", saved
    points_before = _cmd(plugin, "robot_point_list", {"device_id": "r1"})
    attempts = (
        ("robot_point_save", {"device_id": "r1", "point": _point("n", 5.0, 5.0, 5.0)}),
        ("robot_point_delete", {"device_id": "r1", "name": "o"}),
        ("robot_frame_teach", {"device_id": "r1", "name": "sheet", "origin": "o", "on_x": "x", "in_plane": "p"}),
        ("robot_program_delete", {"device_id": "r1", "name": "p1"}),
    )
    for name, data in attempts:
        res = _cmd(plugin, name, data)
        assert res["status"] == "error", (name, res)
        assert res["message"] == TEXT_BAD_ARGS, (name, res)
    assert _cmd(plugin, "robot_point_list", {"device_id": "r1"}) == points_before
    assert _cmd(plugin, "robot_frame_list", {"device_id": "r1"})["frames"] == []
    assert _program_file(tmp_path).is_file()
