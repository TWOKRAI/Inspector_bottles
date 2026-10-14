"""Слепые приёмочные тесты ``RobotDataStore`` (T5.2, ``Services/robot_comm/store.py``).

Purpose:
    Закрепить контракт хранилища данных робота по брифу ``tasks/T5.2.md`` (REDS 1..10):
    оптимистичная ревизия (чужая ревизия — отказ, не затирание), атомарная запись через шов
    ``store._replace_file``, изоляция устройств, белый список ключей, невидимость застрявших
    временных файлов, повтор замены при ``PermissionError``.

Как устроено:
    * Модуль ``store`` и классы ошибок берутся в фикстуре/в теле теста, а не на уровне модуля:
      пока ``store.py`` нет, файл СОБИРАЕТСЯ, а каждый тест падает в ``ERROR`` на фикстуре.
    * Каждый вызов хранилища идёт через ``_call``: daemon-поток + ``join(5)``; зависание —
      ``pytest.fail``, исключение вызова поднимается тем же объектом.
    * Гонка (REDS 2) — рандеву ВНУТРИ шва замены, не на входе в метод.
    * Ожидания — литералы из брифа. Исключение: ревизия, возвращённая ``write``, и sha256 от
      байтов файла (ревизия по DESIGN п.3 — ``sha256(байты).hexdigest()``, считается тестом
      независимо, а не вызовом ``compute_rev`` хранилища).

Намеренно НЕ покрыто (тесты автора, ``test_store.py``): замок после исключения, читатель
параллельно с писателями, гонка ``Prog``/``prog``, относительный ``root``, битые файлы и
``StoreDocumentInvalid``, кириллица в теле, литерал ``compute_rev``. Имена программ
``con``/``prn``/``aux``/``com1..9``/``lpt1..9`` не используются нигде (чтение ``con.yaml``
блокируется навсегда, ``COM7`` — настоящий порт стенда).
"""

from __future__ import annotations

import hashlib
import importlib
import itertools
import os
import threading
import time
from pathlib import Path

import pytest
import yaml

from Services.robot_comm import errors

_KEY_TEXT = "Недопустимое имя данных робота"
_CONFLICT_TEXT = "Данные робота изменены с момента чтения"


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
        pytest.fail("вызов хранилища висит > 5 с")
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["result"]


def _tmp_names(directory: Path) -> list[str]:
    """Имена временных файлов в каталоге (``iterdir`` + ``endswith``, не ``glob``: он пропускает точку)."""
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def mod():
    """Модуль ``Services.robot_comm.store`` (нет файла — ERROR на каждом тесте)."""
    return importlib.import_module("Services.robot_comm.store")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "robot"


@pytest.fixture
def store(mod, root: Path):
    return mod.RobotDataStore(root)


# ---------------------------------------------------------------------------
# REDS 1
# ---------------------------------------------------------------------------


def test_second_writer_same_rev_refused(store, root: Path) -> None:
    # base_rev — keyword-only без умолчания (DESIGN п.1): ни пропуск, ни позиционная передача не проходят.
    with pytest.raises(TypeError):
        _call(store.write, "r9", "params", {"v": 0})
    with pytest.raises(TypeError):
        _call(store.write, "r9", "params", {"v": 0}, None)
    with pytest.raises(TypeError):
        _call(store.write_program, "r9", "p1", {"v": 0})
    assert not (root / "r9").exists()

    # документ
    r0 = _call(store.write, "r1", "params", {"v": 1}, base_rev=None)
    rev_a = _call(store.write, "r1", "params", {"v": 2}, base_rev=r0)
    assert isinstance(rev_a, str)
    assert rev_a != r0
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.write, "r1", "params", {"v": 3}, base_rev=r0)
    assert ei.value.current_rev == rev_a
    assert yaml.safe_load((root / "r1" / "params.yaml").read_bytes()) == {"v": 2}

    # программа
    p0 = _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)
    prev_a = _call(store.write_program, "r1", "p1", {"v": 2}, base_rev=p0)
    assert isinstance(prev_a, str)
    assert prev_a != p0
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.write_program, "r1", "p1", {"v": 3}, base_rev=p0)
    assert ei.value.current_rev == prev_a
    assert yaml.safe_load((root / "r1" / "programs" / "p1.yaml").read_bytes()) == {"v": 2}


# ---------------------------------------------------------------------------
# REDS 2
# ---------------------------------------------------------------------------


def test_concurrent_writers_same_rev_exactly_one_wins(mod, store, root: Path, monkeypatch) -> None:
    r0 = _call(store.write, "r1", "params", {"v": 1}, base_rev=None)  # засев ДО подмены шва

    real = os.replace
    entered = threading.Event()
    release = threading.Event()
    counter = itertools.count(1)
    counter_lock = threading.Lock()

    def fake(src: str, dst: str) -> None:
        with counter_lock:
            n = next(counter)
        if n == 1:
            entered.set()
            release.wait(5)
        real(src, dst)

    monkeypatch.setattr(mod, "_replace_file", fake)

    results: dict[str, tuple[str, object]] = {}

    def run(tag: str) -> None:
        try:
            results[tag] = ("ok", store.write("r1", "params", {"w": tag}, base_rev=r0))
        except BaseException as exc:  # noqa: BLE001
            results[tag] = ("err", exc)

    a = threading.Thread(target=run, args=("A",), daemon=True)
    b: threading.Thread | None = None
    try:
        a.start()
        if not entered.wait(5):
            pytest.fail("писатель A не дошёл до замены файла")
        b = threading.Thread(target=run, args=("B",), daemon=True)
        b.start()
        b.join(timeout=1.0)  # B либо ждёт замок документа, либо (при дефекте) уже прошёл мимо A
    finally:
        release.set()
    a.join(5)
    b.join(5)
    assert not a.is_alive(), "писатель A завис"
    assert not b.is_alive(), "писатель B завис"

    assert results["A"][0] == "ok", results
    assert isinstance(results["A"][1], str)
    assert results["B"][0] == "err", results
    assert isinstance(results["B"][1], errors.RevisionConflict)
    assert results["B"][1].current_rev == results["A"][1]
    assert yaml.safe_load((root / "r1" / "params.yaml").read_bytes()) == {"w": "A"}


# ---------------------------------------------------------------------------
# REDS 3
# ---------------------------------------------------------------------------


def test_create_and_external_edit_conflict(store, root: Path) -> None:
    path = root / "r1" / "params.yaml"
    r0 = _call(store.write, "r1", "params", {"v": 1}, base_rev=None)
    before = path.read_bytes()

    # создание (base_rev=None) при существующем файле
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.write, "r1", "params", {"v": 2}, base_rev=None)
    assert ei.value.current_rev is not None
    assert ei.value.current_rev == r0
    assert str(ei.value) == _CONFLICT_TEXT
    assert path.read_bytes() == before

    # строка при отсутствующем файле
    missing = root / "r1" / "points.yaml"
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.write, "r1", "points", {"v": 2}, base_rev="x")
    assert ei.value.current_rev is None
    assert not missing.exists()

    # файл переписан мимо хранилища
    path.write_bytes(b"v: 99\n")
    with pytest.raises(errors.RevisionConflict) as ei:
        _call(store.write, "r1", "params", {"v": 3}, base_rev=r0)
    current = _call(store.read, "r1", "params")
    assert current.rev is not None
    assert current.rev != r0
    assert ei.value.current_rev == current.rev
    assert path.read_bytes() == b"v: 99\n"
    assert current.body == {"v": 99}


# ---------------------------------------------------------------------------
# REDS 4
# ---------------------------------------------------------------------------


def test_failed_replace_keeps_previous_bytes(mod, store, root: Path, monkeypatch) -> None:
    path = root / "r1" / "params.yaml"
    r0 = _call(store.write, "r1", "params", {"keep": 1}, base_rev=None)  # засев ДО подмены шва
    assert path.read_bytes() == b"keep: 1\n"

    injected = OSError("injected")

    def fake(src: str, dst: str) -> None:
        raise injected

    monkeypatch.setattr(mod, "_replace_file", fake)
    with pytest.raises(OSError) as ei:
        _call(store.write, "r1", "params", {"keep": 2}, base_rev=r0)
    assert ei.value is injected

    assert path.read_bytes() == b"keep: 1\n"
    assert path.read_bytes() != b""
    # сразу после сбоя и ДО любой успешной записи
    assert _tmp_names(root / "r1") == []
    assert _call(store.read, "r1", "params").rev == r0

    # без подмены: замок отпущен, та же base_rev проходит
    monkeypatch.undo()
    r1 = _call(store.write, "r1", "params", {"keep": 2}, base_rev=r0)
    assert isinstance(r1, str)
    assert r1 != r0
    assert path.read_bytes() == b"keep: 2\n"


# ---------------------------------------------------------------------------
# REDS 5
# ---------------------------------------------------------------------------


def test_replace_gets_sibling_tmp_with_new_bytes(mod, store, root: Path, monkeypatch) -> None:
    path = root / "r1" / "params.yaml"
    _call(store.write, "r1", "params", {"v": 1}, base_rev=None)  # засев ДО подмены шва
    old = path.read_bytes()
    assert old == b"v: 1\n"
    r0 = _call(store.read, "r1", "params").rev

    real = os.replace
    seen: list[dict[str, object]] = []

    def fake(src: str, dst: str) -> None:
        seen.append(
            {
                "src": src,
                "dst": dst,
                "src_bytes": Path(src).read_bytes(),
                "dst_bytes": Path(dst).read_bytes(),
            }
        )
        real(src, dst)

    monkeypatch.setattr(mod, "_replace_file", fake)
    new_rev = _call(store.write, "r1", "params", {"v": 2}, base_rev=r0)

    assert len(seen) == 1
    call = seen[0]
    src, dst = str(call["src"]), str(call["dst"])
    assert Path(src).parent == Path(dst).parent
    assert src != dst
    assert Path(src).name.startswith(".params.yaml.")
    assert Path(src).name.endswith(".tmp")
    assert yaml.safe_load(call["src_bytes"]) == {"v": 2}
    assert call["dst_bytes"] == old
    # итог: новые байты на месте, tmp нет, ревизия — sha256 новых байтов
    assert path.read_bytes() == call["src_bytes"]
    assert _tmp_names(root / "r1") == []
    assert new_rev == _sha256(path.read_bytes())


# ---------------------------------------------------------------------------
# REDS 6
# ---------------------------------------------------------------------------


def test_two_devices_do_not_see_each_other(mod, store, root: Path) -> None:
    for doc in ("params", "points", "frames", "calibration"):
        _call(store.write, "r1", doc, {"doc": doc}, base_rev=None)
    _call(store.write_program, "r1", "p1", {"prog": 1}, base_rev=None)
    r1_params = root / "r1" / "params.yaml"
    r1_before = r1_params.read_bytes()

    empty = mod.StoredDoc(None, None)
    for doc in ("params", "points", "frames", "calibration"):
        assert _call(store.read, "r2", doc) == empty
    assert _call(store.read_program, "r2", "p1") == empty
    assert _call(store.list_programs, "r2") == []
    assert not (root / "r2").exists()  # чтение каталогов не создаёт

    r2_rev = _call(store.write, "r2", "params", {"v": 7}, base_rev=None)
    assert isinstance(r2_rev, str)
    assert r1_params.read_bytes() == r1_before

    r2_params = root / "r2" / "params.yaml"
    r2_before = r2_params.read_bytes()
    with pytest.raises(errors.RevisionConflict):
        _call(store.write, "r1", "params", {"v": 8}, base_rev="0" * 64)
    assert r2_params.read_bytes() == r2_before
    assert r1_params.read_bytes() == r1_before


# ---------------------------------------------------------------------------
# REDS 7
# ---------------------------------------------------------------------------

_BAD_DEVICE_IDS: list[object] = [
    "",
    ".",
    "..",
    "../x",
    "..\\x",
    "a/b",
    "a\\b",
    "D:x",
    "C:\\x",
    "R1",
    "r 1",
    "r.1",
    "r1\n",
    "con",
    "NUL",
    "com1",
    "lpt9",
    "a" * 65,
    5,
    None,
]
_DRIVE_IDS = {"D:x", "C:\\x"}  # запись при сломанной проверке ушла бы на другой диск — только чтение


def _expect_key_rejected(problems: list[str], label: str, fn, *a, **kw) -> None:
    try:
        _call(fn, *a, **kw)
    except errors.InvalidStoreKey as exc:
        if not isinstance(exc, ValueError):
            problems.append(f"{label}: InvalidStoreKey не ValueError")
        elif str(exc) != _KEY_TEXT:
            problems.append(f"{label}: текст {str(exc)!r}")
    except Exception as exc:  # noqa: BLE001 — Failed (зависание) не Exception и уходит наружу
        problems.append(f"{label}: ждали InvalidStoreKey, пришло {type(exc).__name__}: {exc}")
    else:
        problems.append(f"{label}: исключения нет")


def test_bad_device_ids_rejected_without_disk(store, tmp_path: Path) -> None:
    problems: list[str] = []
    for bad in _BAD_DEVICE_IDS:
        _expect_key_rejected(problems, f"read({bad!r})", store.read, bad, "params")
        _expect_key_rejected(problems, f"read_program({bad!r})", store.read_program, bad, "p1")
        _expect_key_rejected(problems, f"list_programs({bad!r})", store.list_programs, bad)
        if bad in _DRIVE_IDS:
            continue
        _expect_key_rejected(problems, f"write({bad!r})", store.write, bad, "params", {"v": 1}, base_rev=None)
        _expect_key_rejected(
            problems, f"write_program({bad!r})", store.write_program, bad, "p1", {"v": 1}, base_rev=None
        )

    for bad_doc in ("programs", "../params", "Params", "params.yaml"):
        _expect_key_rejected(problems, f"read(doc={bad_doc!r})", store.read, "r1", bad_doc)
        _expect_key_rejected(problems, f"write(doc={bad_doc!r})", store.write, "r1", bad_doc, {"v": 1}, base_rev=None)

    assert problems == []
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# REDS 8
# ---------------------------------------------------------------------------

_BAD_PROGRAM_NAMES = [
    "",
    ".",
    "..",
    ".hidden",
    "a/b",
    "a\\b",
    "../x",
    "D:x",
    "a:b",
    "a ",
    " a",
    "a.",
    "p1\n",
    "nul",
    "NUL",
    "nul.txt",
    "nul .x",
    "com\u00b9",
    "lpt\u00b3",
    "x" * 65,
]
_GOOD_PROGRAM_NAMES = ["draw_1", "a-b.c", "v1..2", "рисунок 1", "x" * 64]


def test_program_names(store, root: Path) -> None:
    problems: list[str] = []
    for bad in _BAD_PROGRAM_NAMES:
        _expect_key_rejected(problems, f"read_program({bad!r})", store.read_program, "r1", bad)
        if bad == "D:x":  # запись ушла бы на другой диск — только чтение
            continue
        _expect_key_rejected(
            problems, f"write_program({bad!r})", store.write_program, "r1", bad, {"v": 1}, base_rev=None
        )
    assert problems == []
    assert not root.exists()  # отказ — до любого обращения к диску

    for name in _GOOD_PROGRAM_NAMES:
        rev = _call(store.write_program, "r1", name, {"n": name}, base_rev=None)
        assert isinstance(rev, str)
    for name in _GOOD_PROGRAM_NAMES:
        got = _call(store.read_program, "r1", name)
        assert got.body == {"n": name}
        assert got.rev is not None

    assert _call(store.list_programs, "r1") == ["a-b.c", "draw_1", "v1..2", "x" * 64, "рисунок 1"]
    # на диске только принятые файлы: отказы ничего не создали (в том числе обходы "../x", "a\\b", "a/b")
    assert sorted(p.name for p in (root / "r1").iterdir()) == ["programs"]
    assert sorted(p.name for p in (root / "r1" / "programs").iterdir()) == sorted(
        f"{n}.yaml" for n in _GOOD_PROGRAM_NAMES
    )


# ---------------------------------------------------------------------------
# REDS 9
# ---------------------------------------------------------------------------


def test_stray_files_invisible(mod, store, root: Path) -> None:
    programs = root / "r1" / "programs"
    programs.mkdir(parents=True)
    strays = {
        root / "r1" / ".params.yaml.zz.tmp": b"garbage",
        programs / ".p1.yaml.qq.tmp": b"garbage",
        programs / "notes.txt": b"garbage",
        programs / ".hidden.yaml": b"garbage",
        programs / "x$.yaml": b"garbage",
    }
    for path, raw in strays.items():
        path.write_bytes(raw)

    _call(store.write_program, "r1", "p1", {"v": 1}, base_rev=None)

    assert _call(store.read, "r1", "params") == mod.StoredDoc(None, None)
    listed = _call(store.list_programs, "r1")
    assert listed == ["p1"]
    for name in listed:
        got = _call(store.read_program, "r1", name)
        assert got.body == {"v": 1}
    # хранилище застрявшие файлы не чистит (DESIGN п.7)
    for path, raw in strays.items():
        assert path.read_bytes() == raw


# ---------------------------------------------------------------------------
# REDS 10
# ---------------------------------------------------------------------------


def test_replace_permission_error_retry(mod, store, root: Path, monkeypatch) -> None:
    # засев трёх устройств ДО подмены шва
    r_a = _call(store.write, "r1", "params", {"v": 1}, base_rev=None)
    r_b = _call(store.write, "r2", "params", {"v": 1}, base_rev=None)
    r_c = _call(store.write, "r3", "params", {"v": 1}, base_rev=None)
    real = os.replace

    # (a) два PermissionError, затем успех
    calls_a: list[int] = []

    def fake_a(src: str, dst: str) -> None:
        calls_a.append(1)
        if len(calls_a) <= 2:
            raise PermissionError("injected")
        real(src, dst)

    monkeypatch.setattr(mod, "_replace_file", fake_a)
    rev = _call(store.write, "r1", "params", {"v": 2}, base_rev=r_a)
    assert isinstance(rev, str)
    assert len(calls_a) == 3
    assert yaml.safe_load((root / "r1" / "params.yaml").read_bytes()) == {"v": 2}
    assert _tmp_names(root / "r1") == []

    # (b) PermissionError всегда: ≤ 3.0 с, старые байты, tmp нет (до любой успешной записи)
    calls_b: list[int] = []
    path_b = root / "r2" / "params.yaml"
    before_b = path_b.read_bytes()

    def fake_b(src: str, dst: str) -> None:
        calls_b.append(1)
        raise PermissionError("injected")

    monkeypatch.setattr(mod, "_replace_file", fake_b)
    t0 = time.monotonic()
    with pytest.raises(PermissionError):
        _call(store.write, "r2", "params", {"v": 2}, base_rev=r_b)
    elapsed = time.monotonic() - t0
    assert elapsed <= 3.0
    assert elapsed >= 1.4  # паузы (0.05, 0.1, 0.2, 0.4, 0.8) = 1.55 с — повтор реально ждёт
    assert len(calls_b) == 6  # 5 повторов с паузами + последняя попытка без перехвата (DESIGN п.6)
    assert path_b.read_bytes() == before_b
    assert _tmp_names(root / "r2") == []

    # (c) OSError, не PermissionError: ровно один вызов шва, без повторов
    calls_c: list[int] = []
    path_c = root / "r3" / "params.yaml"
    before_c = path_c.read_bytes()

    def fake_c(src: str, dst: str) -> None:
        calls_c.append(1)
        raise OSError("injected")

    monkeypatch.setattr(mod, "_replace_file", fake_c)
    with pytest.raises(OSError) as ei:
        _call(store.write, "r3", "params", {"v": 2}, base_rev=r_c)
    assert not isinstance(ei.value, PermissionError)
    assert len(calls_c) == 1
    assert path_c.read_bytes() == before_c
    assert _tmp_names(root / "r3") == []
