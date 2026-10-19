"""Тесты автора T5.3b: удаление программы, замки документов, форматы данных робота.

Purpose:
    Закрыть то, что слепая приёмка (``test_robot_data_acceptance.py``) намеренно не покрыла: шов ``_remove_file`` и
    ``PermissionError``, замок после отказа, плохие ключи без обращения к диску, кириллица, пустота ``_locks``
    после операций, отказы форматов (параметры, точки, СК, программы) и проход ``robot_data.delete_program``.

Как устроено:
    * Вызовы, которые могут зависнуть, идут через ``_call`` (daemon-поток + ``join(5)``).
    * Паузы повтора ``_REPLACE_PAUSES`` подменяются нулями: повторов столько же, ждать не нужно.
    * Ожидания — литералы; sha256 считается тестом независимо от ``compute_rev``.
    * Имена ``con``/``prn``/``aux``/``com1..9``/``lpt1..9`` не используются (T5.2: зарезервированы Windows).
"""

from __future__ import annotations

import hashlib
import importlib
import threading
from pathlib import Path

import pytest
import yaml

from Services.robot_comm import errors, robot_data
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.programs.program import FrameDef, Move, Point, Program

_INVALID_TEXT = "Данные робота не прошли проверку"
_ZERO_PAUSES = (0.0, 0.0, 0.0, 0.0, 0.0)


def _call(fn, *a, **kw):
    """Вызвать ``fn`` в daemon-потоке; не вернулся за 5 с — ``pytest.fail``; исключение — тем же объектом."""
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["result"] = fn(*a, **kw)
        except BaseException as exc:  # noqa: BLE001 — передаём наружу тем же объектом
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(5)
    if t.is_alive():
        pytest.fail("вызов висит > 5 с")
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["result"]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _full_values(**changed: int) -> dict[str, int]:
    """Полная карта параметров (умолчания таблицы) с точечными заменами — вход для ``save_params``."""
    values = {n: int(PARAMS[PARAM_ID[n]]["default"]) for n in robot_data._VALUE_NAMES}
    values.update(changed)
    return values


@pytest.fixture
def mod():
    """Модуль ``Services.robot_comm.store``."""
    return importlib.import_module("Services.robot_comm.store")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "robot"


@pytest.fixture
def store(mod, root: Path):
    return mod.RobotDataStore(root)


# ---------------------------------------------------------------------------
# delete_program: шов _remove_file и PermissionError
# ---------------------------------------------------------------------------


def test_delete_retries_permission_error_then_succeeds(mod, store, root: Path, monkeypatch) -> None:
    rev = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    path = root / "r1" / "programs" / "p1.yaml"
    monkeypatch.setattr(mod, "_REPLACE_PAUSES", _ZERO_PAUSES)
    real = mod._remove_file
    attempts: list[str] = []

    def flaky(p: str) -> None:
        attempts.append(p)
        if len(attempts) <= 2:
            raise PermissionError("занят")
        real(p)

    monkeypatch.setattr(mod, "_remove_file", flaky)
    assert _call(store.delete_program, "r1", "p1", base_rev=rev) is None
    assert len(attempts) == 3
    assert not path.exists()


def test_delete_permission_error_always_propagates_file_intact(mod, store, root: Path, monkeypatch) -> None:
    rev = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    path = root / "r1" / "programs" / "p1.yaml"
    before = path.read_bytes()
    monkeypatch.setattr(mod, "_REPLACE_PAUSES", _ZERO_PAUSES)
    attempts: list[int] = []

    def always(_p: str) -> None:
        attempts.append(1)
        raise PermissionError("занят")

    monkeypatch.setattr(mod, "_remove_file", always)
    with pytest.raises(PermissionError):
        _call(store.delete_program, "r1", "p1", base_rev=rev)
    assert len(attempts) == 6  # 5 пауз + последняя попытка без перехвата
    assert path.read_bytes() == before
    assert len(store._locks) == 0  # замок отпущен и после сбоя


def test_delete_other_oserror_is_not_retried(mod, store, root: Path, monkeypatch) -> None:
    rev = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    monkeypatch.setattr(mod, "_REPLACE_PAUSES", _ZERO_PAUSES)
    attempts: list[int] = []

    def broken(_p: str) -> None:
        attempts.append(1)
        raise OSError("диск")

    monkeypatch.setattr(mod, "_remove_file", broken)
    with pytest.raises(OSError, match="диск"):
        _call(store.delete_program, "r1", "p1", base_rev=rev)
    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# delete_program: замок, ключи, кириллица
# ---------------------------------------------------------------------------


def test_lock_released_after_delete_conflict(store, root: Path) -> None:
    r0 = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    with pytest.raises(errors.RevisionConflict):
        _call(store.delete_program, "r1", "p1", base_rev="0" * 64)
    # замок документа свободен: запись и удаление не виснут (`_call` падает через 5 с)
    r1 = _call(store.write_program, "r1", "p1", {"v": 2}, base_rev=r0)
    assert _call(store.delete_program, "r1", "p1", base_rev=r1) is None
    assert len(store._locks) == 0


def test_delete_missing_file_conflicts_even_with_none_base_rev(store, root: Path) -> None:
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.delete_program, "r1", "ghost", base_rev=None)
    assert ei.value.current_rev is None
    assert not root.exists()  # отказ каталогов не создаёт


@pytest.mark.parametrize("name", ["../x", "a/b", "..", "", " p", "p ", 5, None])
def test_delete_bad_program_name_refused_before_disk(mod, store, root: Path, monkeypatch, name) -> None:
    removed: list[str] = []
    monkeypatch.setattr(mod, "_remove_file", removed.append)
    with pytest.raises(errors.InvalidStoreKey):
        _call(store.delete_program, "r1", name, base_rev=None)
    assert removed == []
    assert not root.exists()


@pytest.mark.parametrize("device_id", ["R1", "../r1", "", "r 1", 7, None])
def test_delete_bad_device_refused_before_disk(store, root: Path, device_id) -> None:
    with pytest.raises(errors.InvalidStoreKey):
        _call(store.delete_program, device_id, "p1", base_rev=None)
    assert not root.exists()


def test_delete_cyrillic_program_round_trip(store, root: Path) -> None:
    name = "Программа 1"
    rev = _call(store.write_program, "r1", name, {"v": 1}, base_rev=None)
    assert _call(store.list_programs, "r1") == [name]
    assert _call(store.delete_program, "r1", name, base_rev=rev) is None
    assert _call(store.list_programs, "r1") == []
    assert not (root / "r1" / "programs" / f"{name}.yaml").exists()


def test_locks_empty_after_operations(store) -> None:
    r0 = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    _call(store.read_program, "r1", "p1")
    _call(store.read_program, "r1", "nothing")
    _call(store.write, "r1", "points", {"version": 1, "points": []}, base_rev=None)
    _call(store.delete_program, "r1", "p1", base_rev=r0)
    assert len(store._locks) == 0  # инвариант `_doc_lock`: без операций в полёте словарь пуст


def test_new_lock_seam_is_called_per_new_document(mod, store, monkeypatch) -> None:
    created: list[int] = []
    real_new_lock = mod._new_lock

    def counting():
        created.append(1)
        return real_new_lock()

    monkeypatch.setattr(mod, "_new_lock", counting)
    _call(store.read_program, "r1", "p1")
    _call(store.read_program, "r1", "p1")  # первый замок умер с выходом из `with` — второй вызов создаёт новый
    assert len(created) == 2


# ---------------------------------------------------------------------------
# параметры
# ---------------------------------------------------------------------------


def test_params_overrides_unknown_name_refused(store, root: Path) -> None:  # b-I10
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.load_params, store, "r1", overrides={"P_NOPE": 1})
    assert ei.value.rev is None
    assert str(ei.value) == _INVALID_TEXT
    # метка ПК живёт в поле `epoch`, не в `values`
    with pytest.raises(errors.RobotDataInvalid):
        _call(robot_data.load_params, store, "r1", overrides={"P_CONFIG_EPOCH": 5})
    assert not root.exists()


@pytest.mark.parametrize(
    "overrides, epoch_default",
    [({"P_SPD_DEFAULT": 500}, 1), ({"P_SPD_DEFAULT": 50.0}, 1), ({"P_SPD_DEFAULT": True}, 1), ({}, 0), ({}, 65536)],
)
def test_params_overrides_and_epoch_default_validated(store, overrides, epoch_default) -> None:
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.load_params, store, "r1", overrides=overrides, epoch_default=epoch_default)
    assert ei.value.rev is None


def test_overrides_not_applied_when_file_exists(store) -> None:
    _call(robot_data.save_params, store, "r1", _full_values(P_SPD_DEFAULT=55), 2, base_rev=None)
    doc = _call(robot_data.load_params, store, "r1", overrides={"P_SPD_DEFAULT": 70})  # файл — источник истины
    assert doc.values["P_SPD_DEFAULT"] == 55
    assert doc.epoch == 2


@pytest.mark.parametrize("overrides", [{"P_NOPE": 1}, {"P_SPD_DEFAULT": 500}, {"P_SPD_DEFAULT": True}])
def test_overrides_checked_when_file_exists(store, overrides) -> None:
    _call(robot_data.save_params, store, "r1", _full_values(P_SPD_DEFAULT=55), 2, base_rev=None)
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.load_params, store, "r1", overrides=overrides)
    assert ei.value.rev is None  # ошибка вызывающего, не файла


def test_params_partial_file_fills_defaults(store, root: Path) -> None:
    path = root / "r1" / "params.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"version: 1\nepoch: 4\nvalues:\n  P_SPD_JOG: 20\n")
    doc = _call(robot_data.load_params, store, "r1")
    assert doc.values["P_SPD_JOG"] == 20
    assert doc.values["P_SPD_DEFAULT"] == 80  # не в файле -> умолчание таблицы
    assert doc.epoch == 4


@pytest.mark.parametrize(
    "text",
    [
        "version: 1\nepoch: 1\n",  # нет values
        "version: 1\nvalues: {}\n",  # нет epoch
        "epoch: 1\nvalues: {}\n",  # нет version
        "version: 1\nepoch: 1\nvalues: {}\nextra: 1\n",  # лишний ключ
        "version: true\nepoch: 1\nvalues: {}\n",  # bool не версия
        "version: 1\nepoch: true\nvalues: {}\n",  # bool не метка
        "version: 1\nepoch: 1.0\nvalues: {}\n",  # дробное не метка
        "version: 1\nepoch: 1\nvalues: [1]\n",  # values не словарь
        "version: 1\nepoch: 1\nvalues:\n  P_SPD_DEFAULT: 50.0\n",  # сырое — целое
        "version: 1\nepoch: 1\nvalues:\n  P_SPD_DEFAULT: '50'\n",
        "version: 1\nepoch: 1\nvalues:\n  P_CONFIG_EPOCH: 5\n",  # метка — отдельное поле
    ],
)
def test_params_malformed_file_refused_with_rev(store, root: Path, text: str) -> None:
    path = root / "r1" / "params.yaml"
    path.parent.mkdir(parents=True)
    raw = text.encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.load_params, store, "r1")
    assert ei.value.rev == _sha256(raw)


def test_params_not_a_mapping_file_raises_store_error(store, root: Path) -> None:
    path = root / "r1" / "params.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"- 1\n- 2\n")
    with pytest.raises(errors.StoreDocumentInvalid):  # ошибка хранилища не оборачивается
        _call(robot_data.load_params, store, "r1")


def test_save_params_invalid_refused_before_disk(store, root: Path) -> None:
    for values, epoch in (
        (_full_values(P_NOPE=1), 1),
        (_full_values(P_SPD_DEFAULT=0), 1),
        (_full_values(P_SPD_DEFAULT=101), 1),
        (_full_values(P_CONFIG_EPOCH=3), 1),
        (_full_values(P_SPD_DEFAULT=50), 0),
        (_full_values(P_SPD_DEFAULT=50), 65536),
    ):
        with pytest.raises(errors.RobotDataInvalid) as ei:
            _call(robot_data.save_params, store, "r1", values, epoch, base_rev=None)
        assert ei.value.rev is None, (values, epoch)
    assert not root.exists()


def test_save_params_rejects_partial_map(store, root: Path) -> None:
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.save_params, store, "r1", {"P_SPD_DEFAULT": 50}, 1, base_rev=None)
    assert ei.value.rev is None
    assert not root.exists()  # диск не тронут
    one_missing = _full_values()
    del one_missing["P_SPD_JOG"]
    with pytest.raises(errors.RobotDataInvalid):
        _call(robot_data.save_params, store, "r1", one_missing, 1, base_rev=None)
    assert not root.exists()


def test_save_params_full_map_round_trip(store) -> None:
    rev = _call(robot_data.save_params, store, "r1", _full_values(P_SPD_JOG=20), 3, base_rev=None)
    doc = _call(robot_data.load_params, store, "r1")
    assert doc.rev == rev
    assert doc.epoch == 3
    assert doc.values["P_SPD_JOG"] == 20
    assert doc.values == _full_values(P_SPD_JOG=20)


def test_param_source_propagates_invalid_file(store, root: Path) -> None:
    path = root / "r1" / "params.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"version: 1\nepoch: 1\nvalues:\n  P_NOPE: 1\n")
    source = robot_data.make_param_source(store, "r1")
    with pytest.raises(errors.RobotDataInvalid):
        _call(source)


def test_param_source_without_file_uses_overrides_and_returns_copy(store) -> None:
    overrides = {"P_SPD_DEFAULT": 50}
    source = robot_data.make_param_source(store, "r1", overrides=overrides, epoch_default=7)
    overrides["P_SPD_DEFAULT"] = 60  # запомнена копия
    values, epoch = _call(source)
    assert values["P_SPD_DEFAULT"] == 50
    assert epoch == 7
    values["P_SPD_DEFAULT"] = 1  # результат — копия: следующий вызов не видит правки
    assert _call(source)[0]["P_SPD_DEFAULT"] == 50


# ---------------------------------------------------------------------------
# точки, СК, программы
# ---------------------------------------------------------------------------

_PA = Point(name="a", x=300, y=-210, z=-40, rz=-100, hand=1)
_SHEET = FrameDef(name="sheet", origin=(0, 0, 0), on_x=(100, 0, 0), in_plane=(0, 100, 0))


def _put(store, doc: str, body: dict) -> str:
    return store.write("r1", doc, body, base_rev=None)


def test_load_without_files_is_empty(store, root: Path) -> None:
    assert _call(robot_data.load_points, store, "r1") == ({}, None)
    assert _call(robot_data.load_frames, store, "r1") == ({}, None)
    assert _call(robot_data.load_program, store, "r1", "p1") == (None, None)
    assert not root.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"version": 2, "points": []},
        {"version": 1},  # нет points
        {"version": 1, "points": {}},  # не список
        {"version": 1, "points": [], "extra": 1},
        {"version": 1, "points": [5]},  # элемент не словарь
        {"version": 1, "points": [{"name": "a"}]},  # нет полей
        {"version": 1, "points": [_PA.to_dict(), _PA.to_dict()]},  # повтор имени
        {"version": 1, "points": [{**_PA.to_dict(), "x": "300"}]},  # строка вместо числа
    ],
)
def test_load_points_malformed_refused(store, root: Path, body: dict) -> None:
    rev = _put(store, "points", body)
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.load_points, store, "r1")
    assert ei.value.rev == rev


def test_load_frames_degenerate_refused(store) -> None:
    flat = {
        "name": "bad",
        "origin": [0, 0, 0],
        "on_x": [100, 0, 0],
        "in_plane": [200, 0, 0],
    }  # три точки на одной прямой
    rev = _put(store, "frames", {"version": 1, "frames": [flat]})
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.load_frames, store, "r1")
    assert ei.value.rev == rev


def test_save_collections_key_must_match_name(store, root: Path) -> None:
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(robot_data.save_points, store, "r1", {"b": _PA}, base_rev=None)
    assert ei.value.rev is None
    with pytest.raises(errors.RobotDataInvalid):
        _call(robot_data.save_frames, store, "r1", {"other": _SHEET}, base_rev=None)
    assert not root.exists()


def test_save_points_replaces_whole_set_by_revision(store) -> None:
    r0 = _call(robot_data.save_points, store, "r1", {"a": _PA}, base_rev=None)
    pb = Point(name="b", x=1, y=2, z=3, rz=4, hand=0)
    r1 = _call(robot_data.save_points, store, "r1", {"b": pb}, base_rev=r0)  # полная карта: `a` исчезла
    pts, rev = _call(robot_data.load_points, store, "r1")
    assert pts == {"b": pb}
    assert rev == r1
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(robot_data.save_points, store, "r1", {"a": _PA}, base_rev=r0)
    assert ei.value.current_rev == r1


def test_load_program_malformed_bodies_refused(store) -> None:
    bodies = {
        "bad_kind": {"version": 1, "name": "p1", "steps": [{"op": "move", "point": "a", "kind": "NOPE"}]},
        "version_2": {"version": 2, "name": "p1", "steps": []},
        "extra_key": {"version": 1, "name": "p1", "steps": [], "x": 1},
        "no_steps": {"version": 1, "name": "p1"},
    }
    for label, body in bodies.items():
        rev = store.write_program("r1", "p1", body, base_rev=store.read_program("r1", "p1").rev)
        with pytest.raises(errors.RobotDataInvalid) as ei:
            _call(robot_data.load_program, store, "r1", "p1")
        assert ei.value.rev == rev, label


def test_save_program_name_is_file_name_and_bad_name_refused(store, root: Path) -> None:
    prog = Program(name="Программа 1", steps=(Move(point="a", kind="JOINT"),))
    rev = _call(robot_data.save_program, store, "r1", prog, base_rev=None)
    assert (root / "r1" / "programs" / "Программа 1.yaml").is_file()
    assert yaml.safe_load((root / "r1" / "programs" / "Программа 1.yaml").read_bytes())["name"] == "Программа 1"
    assert _call(robot_data.load_program, store, "r1", "Программа 1") == (prog, rev)
    with pytest.raises(errors.InvalidStoreKey):
        _call(robot_data.save_program, store, "r1", Program(name="a/b", steps=()), base_rev=None)


def test_load_collection_lets_unexpected_error_through(store, monkeypatch) -> None:
    _put(store, "points", {"version": 1, "points": [_PA.to_dict()]})

    def boom(cls, d):
        raise KeyError("не доменная ошибка")  # не ValidationError / ValueError / TypeError

    monkeypatch.setattr(Point, "from_dict", classmethod(boom))
    with pytest.raises(KeyError):
        _call(robot_data.load_points, store, "r1")


def test_load_program_lets_unexpected_error_through(store, monkeypatch) -> None:
    prog = Program(name="p1", steps=(Move(point="a", kind="JOINT"),))
    _call(robot_data.save_program, store, "r1", prog, base_rev=None)

    def boom(cls, d):
        raise KeyError("не доменная ошибка")

    monkeypatch.setattr(Program, "from_dict", classmethod(boom))
    with pytest.raises(KeyError):
        _call(robot_data.load_program, store, "r1", "p1")


def test_robot_data_delete_program_passthrough(store) -> None:
    prog = Program(name="p1", steps=(Move(point="a", kind="JOINT"),))
    rev = _call(robot_data.save_program, store, "r1", prog, base_rev=None)
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(robot_data.delete_program, store, "r1", "p1", base_rev="0" * 64)
    assert ei.value.current_rev == rev
    assert _call(robot_data.delete_program, store, "r1", "p1", base_rev=rev) is None
    assert _call(robot_data.load_program, store, "r1", "p1") == (None, None)
