"""Тесты автора T5.3c, часть c1: ветки ``DeviceManager.robot_data``, одно хранилище на процесс, Д2, описания.

Purpose:
    Дополняют слепую приёмку (``test_robot_v2_commands_acceptance.py``): каждая ветка отображения ошибок
    ``robot_data`` (DESIGN 3), ``TEXT_BAD_ARGS`` без входных значений, один ``RobotDataStore`` у плагина и менеджера
    (замок документа один — две записи с одной ``base_rev`` дают ровно одну успешную), отказ Д2 до проверки связи,
    предупреждение при отказе каталога записать описание.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import _ROBOT_V2_DESCRIPTIONS, DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.device_hub.errors import DeviceHubError, DeviceNotFoundError
from Services.device_hub.manager import DeviceManager
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import bounded

TEXT_BAD_ARGS = "неверные аргументы команды робота"
TEXT_STALE = "Данные робота изменены с момента чтения"
TEXT_BAD_KEY = "Недопустимое имя данных робота"
TEXT_NOT_YAML = "Файл данных робота не YAML-словарь"
TEXT_DATA_INVALID = "Данные робота не прошли проверку"
TEXT_ONLY_V2 = "данные робота — только для протокола delta_v2"
TEXT_NO_STORE = "хранилище данных робота не задано"
TEXT_D2 = "запись регистров робота v2 — только командами robot_*"

_STEP = {"op": "move", "point": "a", "kind": "JOINT"}
_PROGRAM = {"name": "p1", "steps": [_STEP]}
_SECRET = "SECRET-VALUE-4417"


def _entry(dev_id: str, protocol: str) -> dict:
    return {
        "id": dev_id,
        "name": dev_id,
        "kind": "robot",
        "protocol": protocol,
        "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
    }


def _manager(tmp_path: Path, *, with_store: bool = True) -> DeviceManager:
    manager = DeviceManager(store=None, robot_store=RobotDataStore(tmp_path / "robot") if with_store else None)
    manager.initialize()
    manager.upsert(_entry("r1", "delta_v2"))
    manager.upsert(_entry("v1", "delta_universal3"))
    return manager


# --------------------------------------------------------------------------------------------------
# Отображение ошибок robot_data (DESIGN 3)
# --------------------------------------------------------------------------------------------------


def test_device_and_store_refusals(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    unknown = manager.robot_data("nope", "point_list", {})
    assert unknown["status"] == "error" and "nope" in unknown["message"]
    assert manager.robot_data("v1", "point_list", {}) == {"status": "error", "message": TEXT_ONLY_V2}
    assert manager.robot_data("r1", "no_such_op", {}) == {
        "status": "error",
        "message": "неизвестная операция данных робота",
    }

    without_store = _manager(tmp_path / "other", with_store=False)
    assert without_store.robot_data("r1", "point_list", {}) == {"status": "error", "message": TEXT_NO_STORE}


def test_revision_conflict_carries_current_rev(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = manager.robot_data("r1", "program_save", {"program": _PROGRAM, "base_rev": None})
    assert first["status"] == "ok"
    stale = manager.robot_data("r1", "program_save", {"program": _PROGRAM, "base_rev": None})
    assert stale == {"status": "error", "message": TEXT_STALE, "current_rev": first["rev"]}
    # удаление несуществующей программы: файла нет -> конфликт с current_rev None
    gone = manager.robot_data("r1", "program_delete", {"name": "absent", "base_rev": None})
    assert gone == {"status": "error", "message": TEXT_STALE, "current_rev": None}


def test_bad_key_data_invalid_and_not_yaml(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert manager.robot_data("r1", "program_get", {"name": "../x"}) == {"status": "error", "message": TEXT_BAD_KEY}

    # points.yaml в формате, который не проходит проверку (version != 1)
    device_dir = tmp_path / "robot" / "r1"
    device_dir.mkdir(parents=True)
    (device_dir / "points.yaml").write_text("version: 2\npoints: []\n", encoding="utf-8")
    assert manager.robot_data("r1", "point_list", {}) == {"status": "error", "message": TEXT_DATA_INVALID}

    # frames.yaml - не YAML-словарь
    (device_dir / "frames.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
    assert manager.robot_data("r1", "frame_list", {}) == {"status": "error", "message": TEXT_NOT_YAML}


@pytest.mark.parametrize(
    ("op", "args"),
    [
        (
            "point_save",
            {"point": {"name": "a", "x": _SECRET, "y": 0.0, "z": 0.0, "rz": 0.0, "hand": 1}, "base_rev": None},
        ),
        ("point_save", {"point": _SECRET, "base_rev": None}),
        ("point_save", {"base_rev": None}),
        ("point_save", {"point": {"name": "a", "x": 0.0, "y": 0.0, "z": 0.0, "rz": 0.0, "hand": 1}, "base_rev": 5}),
        ("point_delete", {"name": 7, "base_rev": None}),
        ("point_delete", {"base_rev": None}),
        ("frame_teach", {"name": "s", "origin": 1, "on_x": "x", "in_plane": "p", "base_rev": None}),
        ("frame_teach", {"name": "s", "origin": "o", "on_x": "x", "in_plane": "p"}),
        ("program_get", {"name": None}),
        ("program_get", {}),
        ("program_save", {"program": {"name": "p1", "steps": _SECRET}, "base_rev": None}),
        ("program_save", {"program": _SECRET, "base_rev": None}),
        ("program_save", {"program": _PROGRAM}),
        ("program_delete", {"name": "p1"}),
    ],
)
def test_bad_args_constant_text_without_input_values(tmp_path: Path, op: str, args: dict) -> None:
    manager = _manager(tmp_path)
    result = manager.robot_data("r1", op, args)
    assert result == {"status": "error", "message": TEXT_BAD_ARGS}
    assert _SECRET not in str(result)
    assert not (tmp_path / "robot" / "r1").exists()  # аргументы проверены до работы с диском


def test_args_not_a_dict_is_bad_args(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert manager.robot_data("r1", "point_list", None) == {"status": "error", "message": TEXT_BAD_ARGS}


def test_param_get_all_scales_to_engineering_units(tmp_path: Path) -> None:
    """P_OVERLAP: scale 10 в таблице протокола - ``value`` = ``raw / 10``, ``raw`` - как в файле."""
    manager = _manager(tmp_path)
    result = manager.robot_data("r1", "param_get_all", {})
    overlap = result["params"]["P_OVERLAP"]
    assert overlap["value"] == overlap["raw"] / 10.0
    assert "P_CONFIG_EPOCH" not in result["params"]


# --------------------------------------------------------------------------------------------------
# Д2
# --------------------------------------------------------------------------------------------------


def test_d2_refusal_before_connection_check(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    assert manager.write_registers("r1", {"HB_PC": 5}) == {"status": "error", "message": TEXT_D2}
    # не v2: прежний путь - «не подключено»; неизвестное устройство - DeviceNotFoundError
    with pytest.raises(DeviceHubError, match="не подключено"):
        manager.write_registers("v1", {"X": 1})
    with pytest.raises(DeviceNotFoundError):
        manager.write_registers("nope", {"X": 1})


# --------------------------------------------------------------------------------------------------
# Плагин: одно хранилище, описания
# --------------------------------------------------------------------------------------------------


def _plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[DeviceHubPlugin, Any]:
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
    registry = tmp_path / "devices.yaml"
    ctx = make_ctx({"registry_path": str(registry)}, tmp_registry=registry)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    return plugin, ctx


def test_one_store_per_process_shared_by_plugin_and_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c-I7: замок документа один — из 8 записей с одной ``base_rev`` проходит ровно одна."""
    plugin, ctx = _plugin(tmp_path, monkeypatch)
    try:
        assert plugin._robot_store is plugin._manager._robot_store  # один экземпляр на процесс
        assert plugin._robot_store._root == tmp_path / "robot"
        assert plugin.cmd_device_upsert(_entry("r1", "delta_v2"))["status"] == "ok"

        # каталог устройства создаётся первой записью: гонка первых записей в НЕСУЩЕСТВУЮЩИЙ каталог даёт ложный
        # InvalidStoreKey в store.py (T5.3b, см. отчёт c1) - здесь проверяется один замок документа, а не она
        first = plugin.cmd_robot_program_save(
            {"device_id": "r1", "program": {"name": "p0", "steps": [_STEP]}, "base_rev": None}
        )
        assert first["status"] == "ok", first

        results: list[dict] = []
        lock = threading.Lock()
        start = threading.Event()

        def save() -> None:
            start.wait(5.0)
            res = plugin.cmd_robot_program_save({"device_id": "r1", "program": _PROGRAM, "base_rev": None})
            with lock:
                results.append(res)

        threads = [threading.Thread(target=save, daemon=True) for _ in range(8)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(10.0)
        assert not any(t.is_alive() for t in threads)
        assert sorted(r["status"] for r in results) == ["error"] * 7 + ["ok"]
        assert [r["message"] for r in results if r["status"] == "error"] == [TEXT_STALE] * 7
    finally:
        bounded(lambda: plugin.shutdown(ctx), 10.0)


def test_robot_data_command_without_device_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin, ctx = _plugin(tmp_path, monkeypatch)
    try:
        assert plugin.cmd_robot_point_list({}) == {"status": "error", "message": "device_id обязателен"}
    finally:
        bounded(lambda: plugin.shutdown(ctx), 10.0)


class _RefusingCatalogue:
    """``CommandManager``-заглушка: ``update_command_metadata`` отказывает для одной команды."""

    def __init__(self, refuse: str) -> None:
        self.refuse = refuse
        self.updated: dict[str, dict] = {}

    def update_command_metadata(self, name: str, metadata: dict) -> bool:
        if name == self.refuse:
            return False
        self.updated[name] = metadata
        return True


def test_descriptions_refused_by_catalogue_only_warn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin, ctx = _plugin(tmp_path, monkeypatch)
    try:
        catalogue = _RefusingCatalogue("robot_stop")
        ctx.command_manager = catalogue
        plugin.start(ctx)  # не бросает: описание, которое каталог не принял, - предупреждение
        assert set(catalogue.updated) == set(_ROBOT_V2_DESCRIPTIONS) - {"robot_stop"}
        assert len(_ROBOT_V2_DESCRIPTIONS) == 21
        warned = [str(call.args[0]) for call in ctx.log_warning.call_args_list]
        assert len(warned) == 1 and "robot_stop" in warned[0]
    finally:
        bounded(lambda: plugin.shutdown(ctx), 10.0)


# --------------------------------------------------------------------------------------------------
# param_get_all отвечает то, что применит драйвер (make_param_source): robot_params и config_epoch записи
# --------------------------------------------------------------------------------------------------


def _manager_with_params(tmp_path: Path, params: dict) -> DeviceManager:
    manager = DeviceManager(store=None, robot_store=RobotDataStore(tmp_path / "robot"))
    manager.initialize()
    manager.upsert({**_entry("r1", "delta_v2"), "params": params})
    return manager


def test_param_get_all_applies_robot_params_and_config_epoch_without_file(tmp_path: Path) -> None:
    manager = _manager_with_params(tmp_path, {"robot_params": {"P_SPD_DEFAULT": 55}, "config_epoch": 7})
    result = manager.robot_data("r1", "param_get_all", {})
    assert result["status"] == "ok"
    assert result["params"]["P_SPD_DEFAULT"] == {"raw": 55, "value": 55.0}
    assert result["epoch"] == 7
    assert result["rev"] is None


def test_param_get_all_file_wins_over_robot_params(tmp_path: Path) -> None:
    manager = _manager_with_params(tmp_path, {"robot_params": {"P_SPD_DEFAULT": 30}, "config_epoch": 7})
    rev = RobotDataStore(tmp_path / "robot").write(
        "r1", "params", {"version": 1, "epoch": 3, "values": {"P_SPD_DEFAULT": 40}}, base_rev=None
    )
    result = manager.robot_data("r1", "param_get_all", {})
    assert result["params"]["P_SPD_DEFAULT"] == {"raw": 40, "value": 40.0}  # override при файле не применяется
    assert result["epoch"] == 3  # метка файла, не config_epoch записи
    assert result["rev"] == rev


def test_param_get_all_bad_override_or_epoch_refused_and_args_cannot_inject(tmp_path: Path) -> None:
    bad_override = _manager_with_params(tmp_path / "a", {"robot_params": {"P_NOPE": 1}})
    assert bad_override.robot_data("r1", "param_get_all", {}) == {"status": "error", "message": TEXT_DATA_INVALID}

    bad_epoch = _manager_with_params(tmp_path / "b", {"config_epoch": _SECRET})
    refused = bad_epoch.robot_data("r1", "param_get_all", {})
    assert refused == {"status": "error", "message": TEXT_DATA_INVALID}
    assert _SECRET not in str(refused)

    plain = _manager_with_params(tmp_path / "c", {})
    injected = plain.robot_data("r1", "param_get_all", {"overrides": {"P_SPD_DEFAULT": 11}, "epoch_default": 9})
    assert injected["params"]["P_SPD_DEFAULT"] == {"raw": 80, "value": 80.0}
    assert injected["epoch"] == 1


def test_store_oserror_answers_constant_text_and_logs_full_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F6 (ревью р.1): ``OSError`` диска -> постоянный текст; путь и имя из команды — только в лог."""
    manager = _manager(tmp_path)
    (tmp_path / "robot" / "r1" / "programs" / "secretname.yaml").mkdir(parents=True)  # файл программы — каталог
    with caplog.at_level("WARNING"):
        answer = manager.robot_data("r1", "program_get", {"name": "secretname"})
    assert answer == {"status": "error", "message": "ошибка хранилища данных робота"}
    assert "secretname" not in answer["message"]
    assert any("secretname" in record.getMessage() for record in caplog.records)  # полный текст — в логе
