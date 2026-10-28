"""Слепые приёмочные тесты M3 (T5.3b): удаление программ с ревизией, предел замков, форматы данных робота.

Purpose:
    Закрепить контракт по брифу ``plans/robot-protocol-v2/tasks/T5.3b.md`` (REDS 1..9):
    ``RobotDataStore.delete_program`` (чужая или устаревшая ревизия — отказ, файл цел; гонка с записью — ровно
    один победитель), рост ``_locks`` ограничен, один замок на документ при сборке мусора, форматы
    ``Services/robot_comm/robot_data.py`` (параметры, точки, СК, программы).

Как устроено:
    * ``robot_data`` и ``errors.RobotDataInvalid`` берутся внутри тела теста (``_rd()`` / ``errors.RobotDataInvalid``):
      пока модуля нет, файл СОБИРАЕТСЯ, а тест падает (FAILED), а не уходит в ERROR на фикстуре.
    * Каждый вызов, который может зависнуть, идёт через ``_call``: daemon-поток + ``join(5)``; зависание —
      ``pytest.fail``, исключение вызова поднимается тем же объектом. Потоки гонок — daemon, ``join`` с дедлайном.
    * Швы — собственные швы брифа: ``store._replace_file`` и ``store._new_lock`` (подмена модульного имени).
    * Ожидания — литералы из брифа. Исключения: умолчания параметров берутся из таблицы ``params_v2.PARAMS``
      (так их определяет DESIGN 4: ``PARAMS[id]["default"]``); sha256 считается тестом независимо от ``compute_rev``.

Намеренно НЕ покрыто (тесты автора, ``test_robot_data.py``): шов ``_remove_file`` и ``PermissionError``, замок
после конфликта удаления, плохое имя в ``delete_program``, кириллица в имени программы. Имена программ
``con``/``prn``/``aux``/``com1..9``/``lpt1..9`` не используются нигде.
"""

from __future__ import annotations

import gc
import hashlib
import importlib
import os
import threading
import tracemalloc
import weakref
from pathlib import Path

import pytest
import yaml

from Services.robot_comm import errors
from Services.robot_comm.core.params_v2 import PARAMS
from Services.robot_comm.programs.program import Action, FrameDef, Move, Point, Program

_INVALID_TEXT = "Данные робота не прошли проверку"


# ---------------------------------------------------------------------------
# Помощники и фикстуры
# ---------------------------------------------------------------------------


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


def _rd():
    """Модуль ``Services.robot_comm.robot_data`` (нет файла — ``ModuleNotFoundError`` внутри теста)."""
    return importlib.import_module("Services.robot_comm.robot_data")


def _defaults() -> dict[str, int]:
    """Умолчания всех параметров таблицы без ``P_CONFIG_EPOCH`` (DESIGN 4: ``PARAMS[id]["default"]``)."""
    return {p["name"]: p["default"] for p in PARAMS.values() if p["name"] != "P_CONFIG_EPOCH"}


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


def _writer(store, tag: str, base_rev: str | None, results: dict, *, name: str = "p1", go=None, collect=False):
    """Daemon-поток: записать программу ``r1/<name>`` с телом ``{"w": tag}``; итог — ``results[tag]``."""

    def run() -> None:
        try:
            if go is not None:
                go.wait(5)
            if collect:
                gc.collect()
            results[tag] = ("ok", store.write_program("r1", name, {"w": tag}, base_rev=base_rev))
        except BaseException as exc:  # noqa: BLE001
            results[tag] = ("err", exc)

    return threading.Thread(target=run, daemon=True)


# ---------------------------------------------------------------------------
# REDS 1
# ---------------------------------------------------------------------------


def test_delete_program_with_current_rev(store, root: Path) -> None:
    path = root / "r1" / "programs" / "p1.yaml"
    rev = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)

    # base_rev — keyword-only без умолчания (DESIGN 1): ни пропуск, ни позиционная передача не проходят.
    with pytest.raises(TypeError):
        _call(store.delete_program, "r1", "p1")
    with pytest.raises(TypeError):
        _call(store.delete_program, "r1", "p1", rev)
    assert path.exists()

    assert _call(store.delete_program, "r1", "p1", base_rev=rev) is None
    assert not path.exists()
    got = _call(store.read_program, "r1", "p1")
    assert got.body is None
    assert got.rev is None
    assert _call(store.list_programs, "r1") == []

    # второй раз — файла нет: отказ, текущая ревизия None
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.delete_program, "r1", "p1", base_rev=rev)
    assert ei.value.current_rev is None


# ---------------------------------------------------------------------------
# REDS 2
# ---------------------------------------------------------------------------


def test_delete_program_stale_rev_refused(store, root: Path) -> None:
    path = root / "r1" / "programs" / "p1.yaml"
    r0 = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    r1 = _call(store.write_program, "r1", "p1", {"v": 2}, base_rev=r0)
    rev_p2 = _call(store.write_program, "r1", "p2", {"v": 9}, base_rev=None)
    before = path.read_bytes()
    before_p2 = (root / "r1" / "programs" / "p2.yaml").read_bytes()
    assert r1 == _sha256(before)  # ревизия — sha256 байтов (T5.2), считается независимо
    assert r0 != r1

    # устаревшая, нулевая, чужая (ревизия p2), None при существующем файле — один и тот же отказ
    for label, bad in (("устаревшая", r0), ("нулевая", "0" * 64), ("чужая p2", rev_p2), ("None", None)):
        with pytest.raises(errors.RevisionConflict) as ei:
            _call(store.delete_program, "r1", "p1", base_rev=bad)
        assert ei.value.current_rev == r1, label
        assert path.read_bytes() == before, label
        assert (root / "r1" / "programs" / "p2.yaml").read_bytes() == before_p2, label
    assert _call(store.list_programs, "r1") == ["p1", "p2"]


# ---------------------------------------------------------------------------
# REDS 3
# ---------------------------------------------------------------------------


def test_delete_races_write_exactly_one_wins(mod, store, root: Path, monkeypatch) -> None:
    r0 = _call(store.write_program, "r1", "p1", {"v": 0}, base_rev=None)  # засев ДО подмены шва

    real = os.replace
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    calls_lock = threading.Lock()

    def fake(src: str, dst: str) -> None:
        with calls_lock:
            calls.append(1)
            n = len(calls)
        if n == 1:
            entered.set()
            release.wait(10)
        real(src, dst)

    monkeypatch.setattr(mod, "_replace_file", fake)

    results: dict[str, tuple[str, object]] = {}

    def run_write() -> None:
        try:
            results["A"] = ("ok", store.write_program("r1", "p1", {"w": "A"}, base_rev=r0))
        except BaseException as exc:  # noqa: BLE001
            results["A"] = ("err", exc)

    def run_delete() -> None:
        try:
            results["B"] = ("ok", store.delete_program("r1", "p1", base_rev=r0))
        except BaseException as exc:  # noqa: BLE001
            results["B"] = ("err", exc)

    a = threading.Thread(target=run_write, daemon=True)
    b = threading.Thread(target=run_delete, daemon=True)
    try:
        a.start()
        if not entered.wait(5):
            pytest.fail("запись A не дошла до замены файла")
        b.start()
        b.join(timeout=1.0)  # B либо ждёт замок документа, либо (при дефекте) уже прошёл мимо A
    finally:
        release.set()
    a.join(5)
    b.join(5)
    assert not a.is_alive(), "запись A зависла"
    assert not b.is_alive(), "удаление B зависло"

    assert results["A"][0] == "ok", results
    assert isinstance(results["A"][1], str)
    assert results["B"][0] == "err", results
    assert isinstance(results["B"][1], errors.RevisionConflict), results
    assert results["B"][1].current_rev == results["A"][1]
    assert yaml.safe_load((root / "r1" / "programs" / "p1.yaml").read_bytes()) == {"w": "A"}
    assert _call(store.list_programs, "r1") == ["p1"]


# ---------------------------------------------------------------------------
# REDS 4
# ---------------------------------------------------------------------------


def test_locks_do_not_grow(mod, store) -> None:
    def reads() -> None:
        for i in range(5000):
            store.read_program("r1", f"p{i}")

    started_here = not tracemalloc.is_tracing()
    tracemalloc.start()
    try:
        gc.collect()
        s0 = tracemalloc.take_snapshot()
        # 5000 ключей, ни одной записи: у верного кода замков в `_locks` не остаётся
        box: dict[str, object] = {}

        def run() -> None:
            try:
                reads()
            except BaseException as exc:  # noqa: BLE001
                box["exc"] = exc

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(60)
        if t.is_alive():
            pytest.fail("5000 чтений висят > 60 с")
        if "exc" in box:
            raise box["exc"]  # type: ignore[misc]
        gc.collect()
        s1 = tracemalloc.take_snapshot()
    finally:
        if started_here:
            tracemalloc.stop()

    # только кадры store.py и weakref.py: остаток в pathlib есть и у верного кода (уточнение стадии 0)
    flt = [tracemalloc.Filter(True, mod.__file__), tracemalloc.Filter(True, weakref.__file__)]
    diffs = s1.filter_traces(flt).compare_to(s0.filter_traces(flt), "filename")
    growth = sum(d.size_diff for d in diffs)
    assert growth < 64 * 1024, f"рост {growth / 1024:.1f} КиБ в store.py/weakref.py за 5000 чтений"


# ---------------------------------------------------------------------------
# REDS 5
# ---------------------------------------------------------------------------


def test_params_defaults_and_overrides_without_file(store, root: Path) -> None:
    rd = _rd()
    expected = _defaults()
    assert expected["P_SPD_DEFAULT"] == 80  # литерал брифа: таблица params_v2 не разошлась

    doc = _call(rd.load_params, store, "r1")
    assert doc.values["P_SPD_DEFAULT"] == 80
    assert "P_CONFIG_EPOCH" not in doc.values
    assert dict(doc.values) == expected
    assert doc.epoch == 1
    assert doc.rev is None
    assert not (root / "r1").exists()  # чтение без файла ничего не создаёт

    doc = _call(rd.load_params, store, "r1", overrides={"P_SPD_DEFAULT": 50}, epoch_default=7)
    assert doc.values["P_SPD_DEFAULT"] == 50
    assert dict(doc.values) == {**expected, "P_SPD_DEFAULT": 50}
    assert doc.epoch == 7
    assert doc.rev is None

    # неизвестное имя в overrides — отказ без ревизии (DESIGN 4)
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(rd.load_params, store, "r1", overrides={"P_NOPE": 1})
    assert ei.value.rev is None


# ---------------------------------------------------------------------------
# REDS 6
# ---------------------------------------------------------------------------


def test_params_file_is_source_of_truth(store, root: Path) -> None:
    rd = _rd()
    path = root / "r1" / "params.yaml"
    full55 = {**_defaults(), "P_SPD_DEFAULT": 55}

    rev = _call(rd.save_params, store, "r1", full55, 3, base_rev=None)
    assert isinstance(rev, str)
    assert rev == _sha256(path.read_bytes())
    raw_doc = yaml.safe_load(path.read_bytes())
    assert raw_doc["version"] == 1
    assert raw_doc["epoch"] == 3
    assert raw_doc["values"]["P_SPD_DEFAULT"] == 55

    # файл есть — overrides не применяются
    doc = _call(rd.load_params, store, "r1", overrides={"P_SPD_DEFAULT": 50})
    assert doc.values["P_SPD_DEFAULT"] == 55
    assert dict(doc.values) == full55
    assert doc.epoch == 3
    assert doc.rev == rev

    source = rd.make_param_source(store, "r1", overrides={"P_SPD_DEFAULT": 50}, epoch_default=9)
    got = _call(source)
    assert isinstance(got, tuple)
    assert got == (full55, 3)

    # источник читает файл на каждый вызов
    full60 = {**_defaults(), "P_SPD_DEFAULT": 60}
    rev2 = _call(rd.save_params, store, "r1", full60, 4, base_rev=rev)
    assert rev2 != rev
    assert _call(source) == (full60, 4)

    # сохранение с чужой ревизией — отказ, файл цел
    before = path.read_bytes()
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(rd.save_params, store, "r1", full55, 3, base_rev=None)
    assert ei.value.current_rev == rev2
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# REDS 7
# ---------------------------------------------------------------------------


def test_params_invalid_file_refused(store, root: Path) -> None:
    rd = _rd()
    assert issubclass(errors.RobotDataInvalid, errors.RobotStoreError)
    path = root / "r1" / "params.yaml"
    path.parent.mkdir(parents=True)

    cases = {
        "неизвестное имя": "version: 1\nepoch: 1\nvalues:\n  P_NOPE: 1\n",
        "сырое выше max (500)": "version: 1\nepoch: 1\nvalues:\n  P_SPD_DEFAULT: 500\n",
        "сырое ниже min (0)": "version: 1\nepoch: 1\nvalues:\n  P_SPD_DEFAULT: 0\n",
        "метка 0": "version: 1\nepoch: 0\nvalues:\n  P_SPD_DEFAULT: 50\n",
        "метка 65536": "version: 1\nepoch: 65536\nvalues:\n  P_SPD_DEFAULT: 50\n",
        "версия 2": "version: 2\nepoch: 1\nvalues:\n  P_SPD_DEFAULT: 50\n",
    }
    problems: list[str] = []
    for label, text in cases.items():
        raw = text.encode("utf-8")
        path.write_bytes(raw)
        try:
            _call(rd.load_params, store, "r1")
        except errors.RobotDataInvalid as exc:
            if exc.rev != _sha256(raw):
                problems.append(f"{label}: rev {exc.rev!r}, ждали ревизию байтов файла")
            if str(exc) != _INVALID_TEXT:
                problems.append(f"{label}: текст {str(exc)!r}")
        except Exception as exc:  # noqa: BLE001 — Failed (зависание) не Exception и уходит наружу
            problems.append(f"{label}: ждали RobotDataInvalid, пришло {type(exc).__name__}: {exc}")
        else:
            problems.append(f"{label}: исключения нет")
    assert problems == []

    # границы допустимого проходят: метка 65535 и max 100; метка 1 и min 1
    path.write_bytes(b"version: 1\nepoch: 65535\nvalues:\n  P_SPD_DEFAULT: 100\n")
    doc = _call(rd.load_params, store, "r1")
    assert doc.epoch == 65535
    assert doc.values["P_SPD_DEFAULT"] == 100
    path.write_bytes(b"version: 1\nepoch: 1\nvalues:\n  P_SPD_DEFAULT: 1\n")
    doc = _call(rd.load_params, store, "r1")
    assert doc.epoch == 1
    assert doc.values["P_SPD_DEFAULT"] == 1


# ---------------------------------------------------------------------------
# REDS 8
# ---------------------------------------------------------------------------


def test_points_frames_programs_round_trip(store, root: Path) -> None:
    rd = _rd()
    pa = Point(name="a", x=300, y=-210, z=-40, rz=-100, hand=1)
    pb = Point(name="b", x=250.5, y=100, z=-20, rz=45, hand=0, frame="sheet")
    sheet = FrameDef(name="sheet", origin=(0, 0, 0), on_x=(100, 0, 0), in_plane=(0, 100, 0))
    prog = Program(name="p1", steps=(Move(point="a", kind="JOINT"),))
    prog3 = Program(name="p3", steps=(Move(point="a", kind="JOINT"), Action(act="SPEED_PCT", value=50)))

    # точки
    rev_pts = _call(rd.save_points, store, "r1", {"a": pa, "b": pb}, base_rev=None)
    assert rev_pts == _sha256((root / "r1" / "points.yaml").read_bytes())
    assert yaml.safe_load((root / "r1" / "points.yaml").read_bytes()) == {
        "version": 1,
        "points": [
            {"name": "a", "x": 300.0, "y": -210.0, "z": -40.0, "rz": -100.0, "hand": 1, "frame": None},
            {"name": "b", "x": 250.5, "y": 100.0, "z": -20.0, "rz": 45.0, "hand": 0, "frame": "sheet"},
        ],
    }
    pts, got_rev = _call(rd.load_points, store, "r1")
    assert pts == {"a": pa, "b": pb}
    assert got_rev == rev_pts

    # СК
    rev_frames = _call(rd.save_frames, store, "r1", {"sheet": sheet}, base_rev=None)
    assert yaml.safe_load((root / "r1" / "frames.yaml").read_bytes()) == {
        "version": 1,
        "frames": [
            {"name": "sheet", "origin": [0.0, 0.0, 0.0], "on_x": [100.0, 0.0, 0.0], "in_plane": [0.0, 100.0, 0.0]}
        ],
    }
    frames, got_rev = _call(rd.load_frames, store, "r1")
    assert frames == {"sheet": sheet}
    assert got_rev == rev_frames

    # программы: имя файла = имя программы
    rev_prog = _call(rd.save_program, store, "r1", prog, base_rev=None)
    _call(rd.save_program, store, "r1", prog3, base_rev=None)
    assert (root / "r1" / "programs" / "p1.yaml").is_file()
    assert _call(store.list_programs, "r1") == ["p1", "p3"]
    loaded, got_rev = _call(rd.load_program, store, "r1", "p1")
    assert loaded == prog
    assert got_rev == rev_prog
    loaded3, _ = _call(rd.load_program, store, "r1", "p3")
    assert loaded3 == prog3
    assert _call(rd.load_program, store, "r1", "nope") == (None, None)

    # запись поверх существующего с чужой ревизией — отказ
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(rd.save_points, store, "r1", {"a": pa}, base_rev=None)
    assert ei.value.current_rev == rev_pts
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(rd.save_frames, store, "r1", {"sheet": sheet}, base_rev=None)
    assert ei.value.current_rev == rev_frames
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(rd.save_program, store, "r1", prog, base_rev=None)
    assert ei.value.current_rev == rev_prog

    # точка с hand: 2 в файле (остальное корректно) — отказ с ревизией этих байтов
    bad_points = {
        "version": 1,
        "points": [{"name": "a", "x": 300.0, "y": -210.0, "z": -40.0, "rz": -100.0, "hand": 2, "frame": None}],
    }
    _call(store.write, "r2", "points", bad_points, base_rev=None)
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(rd.load_points, store, "r2")
    assert ei.value.rev == _sha256((root / "r2" / "points.yaml").read_bytes())
    assert str(ei.value) == _INVALID_TEXT

    # программа с телом `name: p2` в файле p1.yaml (остальное корректно) — отказ
    wrong_name = {"version": 1, "name": "p2", "steps": [{"op": "move", "point": "a", "kind": "JOINT"}]}
    _call(store.write_program, "r2", "p1", wrong_name, base_rev=None)
    with pytest.raises(errors.RobotDataInvalid) as ei:
        _call(rd.load_program, store, "r2", "p1")
    assert ei.value.rev == _sha256((root / "r2" / "programs" / "p1.yaml").read_bytes())
    assert str(ei.value) == _INVALID_TEXT


# ---------------------------------------------------------------------------
# REDS 9
# ---------------------------------------------------------------------------


def test_one_lock_per_document_under_gc(mod, store, root: Path, tmp_path: Path, monkeypatch) -> None:
    # --- часть 1: A держится внутри замены, пока B и C (после gc.collect) ждут замок документа ---
    r0 = _call(store.write_program, "r1", "p1", {"v": 0}, base_rev=None)  # засев ДО подмены шва
    real = os.replace
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    calls_lock = threading.Lock()

    def fake(src: str, dst: str) -> None:
        with calls_lock:
            calls.append(1)
            n = len(calls)
        if n == 1:
            entered.set()
            release.wait(10)
        real(src, dst)

    results: dict[str, tuple[str, object]] = {}
    with monkeypatch.context() as mp:
        mp.setattr(mod, "_replace_file", fake)
        a = _writer(store, "A", r0, results)
        b = _writer(store, "B", r0, results, collect=True)
        c = _writer(store, "C", r0, results, collect=True)
        try:
            a.start()
            if not entered.wait(5):
                pytest.fail("запись A не дошла до замены файла")
            for _ in range(3):
                gc.collect()
            b.start()
            c.start()
            b.join(1.0)
            c.join(1.0)
            calls_while_held = len(calls)
        finally:
            release.set()
        for t in (a, b, c):
            t.join(5)
    assert all(not t.is_alive() for t in (a, b, c)), "поток записи завис"
    assert calls_while_held == 1, "B или C вошли в замену, пока A держит документ"
    assert len(calls) == 1
    assert results["A"][0] == "ok", results
    for tag in ("B", "C"):
        assert results[tag][0] == "err", results
        assert isinstance(results[tag][1], errors.RevisionConflict), results
    assert yaml.safe_load((root / "r1" / "programs" / "p1.yaml").read_bytes()) == {"w": "A"}

    # --- часть 2: 50 повторов «запись -> gc.collect() -> два писателя на один ключ»;
    # ловит зависание и двойную запись, замок не доказывает (шторм потоков под GIL) ---
    prev: str | None = None
    for k in range(50):
        seed = _call(store.write_program, "r1", "loop", {"k": k}, base_rev=prev)
        gc.collect()
        loop_results: dict[str, tuple[str, object]] = {}
        go = threading.Event()
        x = _writer(store, "X", seed, loop_results, name="loop", go=go)
        y = _writer(store, "Y", seed, loop_results, name="loop", go=go)
        x.start()
        y.start()
        go.set()
        x.join(5)
        y.join(5)
        assert not x.is_alive() and not y.is_alive(), f"повтор {k}: поток записи завис"
        oks = [tag for tag, (status, _) in loop_results.items() if status == "ok"]
        assert len(oks) == 1, f"повтор {k}: успешных записей {len(oks)}: {loop_results}"
        other = "Y" if oks[0] == "X" else "X"
        assert isinstance(loop_results[other][1], errors.RevisionConflict), f"повтор {k}: {loop_results}"
        prev = loop_results[oks[0]][1]  # type: ignore[assignment]

    # --- часть 3: шов `_new_lock` — два потока на один ключ создают ровно один замок ---
    root3 = tmp_path / "robot3"
    (root3 / "r1" / "programs").mkdir(parents=True)
    seed_bytes = b"v: 0\n"
    (root3 / "r1" / "programs" / "p1.yaml").write_bytes(seed_bytes)  # мимо хранилища: замка этого ключа ещё не было
    r0_3 = _sha256(seed_bytes)
    store3 = mod.RobotDataStore(root3)
    real_new_lock = mod._new_lock  # нет шва — AttributeError (RED на дереве до реализации)

    barrier = threading.Barrier(2, timeout=1.0)
    broken = threading.Event()
    new_lock_calls: list[int] = []
    entered3 = threading.Event()
    release3 = threading.Event()
    replace_calls: list[int] = []

    def new_lock_wrapper():
        new_lock_calls.append(1)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            broken.set()
        return real_new_lock()

    def fake3(src: str, dst: str) -> None:
        with calls_lock:
            replace_calls.append(1)
            n = len(replace_calls)
        if n == 1:
            entered3.set()
            release3.wait(10)
        real(src, dst)

    results3: dict[str, tuple[str, object]] = {}
    with monkeypatch.context() as mp:
        mp.setattr(mod, "_new_lock", new_lock_wrapper)
        mp.setattr(mod, "_replace_file", fake3)
        go3 = threading.Event()
        t1 = _writer(store3, "A", r0_3, results3, go=go3)
        t2 = _writer(store3, "B", r0_3, results3, go=go3)
        try:
            t1.start()
            t2.start()
            go3.set()
            if not entered3.wait(5):
                pytest.fail("ни один писатель не дошёл до замены файла")
            threading.Event().wait(0.3)  # первый писатель держит документ; второй либо ждёт замок, либо уже прошёл
        finally:
            release3.set()
        t1.join(5)
        t2.join(5)
    assert not t1.is_alive() and not t2.is_alive(), "поток записи завис"
    assert len(new_lock_calls) == 1, f"на один документ создано замков: {len(new_lock_calls)}"
    assert broken.is_set(), "барьер не порвался по сроку: второй создатель замка всё же появился"
    oks3 = [tag for tag, (status, _) in results3.items() if status == "ok"]
    assert len(oks3) == 1, results3
    loser = "B" if oks3[0] == "A" else "A"
    assert isinstance(results3[loser][1], errors.RevisionConflict), results3
    assert results3[loser][1].current_rev == results3[oks3[0]][1]
    assert yaml.safe_load((root3 / "r1" / "programs" / "p1.yaml").read_bytes()) == {"w": oks3[0]}
