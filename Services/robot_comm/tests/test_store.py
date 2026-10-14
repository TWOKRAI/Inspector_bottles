"""Тесты автора ``RobotDataStore`` (T5.2): то, что не покрыла слепая приёмка (``test_store_acceptance.py``).

Покрыто: замок отпускается после сбоя; чтение ждёт замену (замок на чтении); читатель параллельно с писателем
не ловит ``PermissionError`` на замене; замки разных документов независимы; гонка ``prog``/``Prog`` через шов;
относительный ``root``; битые файлы и ``StoreDocumentInvalid``; тело записи не словарь/не сериализуется; чтение
и отказ не создают каталогов; кириллица; литерал ``compute_rev``.

Правила: ожидания — литералы; всё, что может зависнуть, идёт в daemon-потоке с дедлайном; имена программ
``con``/``prn``/``aux``/``com1..9``/``lpt1..9`` не используются (чтение ``con.yaml`` блокируется навсегда).
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import pytest
import yaml

from Services.robot_comm import errors, store

# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _within(seconds: float, fn, *a, **kw):
    """Вызвать ``fn`` в daemon-потоке; не вернулся за ``seconds`` — ``pytest.fail``; исключение — тем же объектом."""
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["result"] = fn(*a, **kw)
        except BaseException as exc:  # noqa: BLE001 — передаём наружу тем же объектом
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        pytest.fail(f"вызов хранилища висит > {seconds} с")
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["result"]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _park_first_replace(monkeypatch):
    """Подменить шов: первый вызов замены встаёт (``entered``) до ``release``, затем настоящая замена."""
    real = os.replace
    entered = threading.Event()
    release = threading.Event()
    state = {"n": 0}
    guard = threading.Lock()

    def fake(src: str, dst: str) -> None:
        with guard:
            state["n"] += 1
            first = state["n"] == 1
        if first:
            entered.set()
            release.wait(5)
        real(src, dst)

    monkeypatch.setattr(store, "_replace_file", fake)
    return entered, release


def _in_thread(results: dict, tag: str, fn, *a, **kw) -> threading.Thread:
    def run() -> None:
        try:
            results[tag] = ("ok", fn(*a, **kw))
        except BaseException as exc:  # noqa: BLE001
            results[tag] = ("err", exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "robot"


@pytest.fixture
def rds(root: Path) -> store.RobotDataStore:
    return store.RobotDataStore(root)


# ---------------------------------------------------------------------------
# Замки
# ---------------------------------------------------------------------------


def test_lock_released_after_failed_write(rds, root: Path, monkeypatch) -> None:
    r0 = rds.write("r1", "params", {"v": 1}, base_rev=None)

    def boom(src: str, dst: str) -> None:
        raise OSError("injected")

    monkeypatch.setattr(store, "_replace_file", boom)
    with pytest.raises(OSError):
        _within(2.0, rds.write, "r1", "params", {"v": 2}, base_rev=r0)
    monkeypatch.undo()

    # замок отпущен: чтение и следующая запись возвращаются быстро, а не висят на замке документа
    assert _within(2.0, rds.read, "r1", "params").rev == r0
    r1 = _within(2.0, rds.write, "r1", "params", {"v": 2}, base_rev=r0)
    assert (root / "r1" / "params.yaml").read_bytes() == b"v: 2\n"
    assert r1 == _sha256(b"v: 2\n")


def test_lock_released_after_conflict(rds) -> None:
    rds.write("r1", "params", {"v": 1}, base_rev=None)
    with pytest.raises(errors.RevisionConflict):
        _within(2.0, rds.write, "r1", "params", {"v": 2}, base_rev=None)
    # после отказа по ревизии замок тоже отпущен
    assert _within(2.0, rds.read, "r1", "params").body == {"v": 1}


def test_read_waits_for_replace_in_flight(rds, monkeypatch) -> None:
    """Чтение берёт замок документа: пока запись в замене, ``read`` не возвращает старые байты мимо замка."""
    r0 = rds.write("r1", "params", {"v": 1}, base_rev=None)
    entered, release = _park_first_replace(monkeypatch)
    results: dict = {}
    writer = _in_thread(results, "w", rds.write, "r1", "params", {"v": 2}, base_rev=r0)
    reader = None
    try:
        assert entered.wait(5), "писатель не дошёл до замены"
        reader = _in_thread(results, "r", rds.read, "r1", "params")
        reader.join(timeout=0.5)
        assert reader.is_alive(), "read вернулся, пока документ в замене"
    finally:
        release.set()
    writer.join(5)
    reader.join(5)
    assert not writer.is_alive()
    assert not reader.is_alive()
    assert results["w"][0] == "ok"
    assert results["r"][0] == "ok"
    assert results["r"][1].body == {"v": 2}


def test_locks_of_different_documents_are_independent(rds, monkeypatch) -> None:
    """Замена одного документа не держит запись другого документа и другого устройства."""
    entered, release = _park_first_replace(monkeypatch)
    results: dict = {}
    writer = _in_thread(results, "a", rds.write, "r1", "params", {"v": 1}, base_rev=None)
    try:
        assert entered.wait(5), "писатель не дошёл до замены"
        other_doc = _within(3.0, rds.write, "r1", "points", {"v": 2}, base_rev=None)
        other_dev = _within(3.0, rds.write, "r2", "params", {"v": 3}, base_rev=None)
        assert isinstance(other_doc, str)
        assert isinstance(other_dev, str)
    finally:
        release.set()
    writer.join(5)
    assert not writer.is_alive()
    assert results["a"][0] == "ok"


def test_reader_never_blocks_replace_with_permission_error(rds, monkeypatch) -> None:
    """200 чтений параллельно с 50 записями: настоящая ``os.replace`` ни разу не получает ``PermissionError``.

    На Windows замена падает, пока цель открыта читателем; хранилище исключает это замком на чтении. Шпион
    ловит ошибку самой ``os.replace`` ДО повтора, поэтому повтор записи её не прячет.
    """
    real = os.replace
    denied: list[BaseException] = []

    def spy(src: str, dst: str) -> None:
        try:
            real(src, dst)
        except PermissionError as exc:
            denied.append(exc)
            raise

    last = {"rev": rds.write("r1", "params", {"i": 0}, base_rev=None)}
    monkeypatch.setattr(store, "_replace_file", spy)
    problems: list[str] = []

    def writer() -> None:
        try:
            for i in range(1, 51):
                last["rev"] = rds.write("r1", "params", {"i": i}, base_rev=last["rev"])
        except BaseException as exc:  # noqa: BLE001
            problems.append(f"writer: {type(exc).__name__}: {exc}")

    def reader() -> None:
        try:
            for _ in range(200):
                got = rds.read("r1", "params")
                if got.body is None or "i" not in got.body:
                    problems.append(f"reader: {got!r}")
        except BaseException as exc:  # noqa: BLE001
            problems.append(f"reader: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 30
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    assert not any(t.is_alive() for t in threads), "потоки не завершились за 30 с"

    assert denied == []
    assert problems == []
    final = rds.read("r1", "params")
    assert final.body == {"i": 50}
    assert final.rev == last["rev"]


def test_case_variants_share_one_lock(rds, root: Path, tmp_path: Path, monkeypatch) -> None:
    """``prog`` и ``Prog`` на нечувствительной к регистру ФС — один файл: второе создание — конфликт, не затирание."""
    (tmp_path / "CaseProbe").write_bytes(b"")
    if not (tmp_path / "caseprobe").exists():
        pytest.skip("ФС чувствительна к регистру: prog и Prog — разные файлы")

    entered, release = _park_first_replace(monkeypatch)
    results: dict = {}
    a = _in_thread(results, "A", rds.write_program, "r1", "prog", {"w": "A"}, base_rev=None)
    b = None
    try:
        assert entered.wait(5), "писатель A не дошёл до замены"
        b = _in_thread(results, "B", rds.write_program, "r1", "Prog", {"w": "B"}, base_rev=None)
        b.join(timeout=1.0)  # B ждёт замок документа; при дефекте уже прошёл мимо A
    finally:
        release.set()
    a.join(5)
    b.join(5)
    assert not a.is_alive()
    assert not b.is_alive()

    assert results["A"][0] == "ok", results
    assert results["B"][0] == "err", results
    assert isinstance(results["B"][1], errors.RevisionConflict)
    assert results["B"][1].current_rev == results["A"][1]
    programs = root / "r1" / "programs"
    assert [p.name for p in programs.iterdir()] == ["prog.yaml"]
    assert yaml.safe_load((programs / "prog.yaml").read_bytes()) == {"w": "A"}


# ---------------------------------------------------------------------------
# Относительный root
# ---------------------------------------------------------------------------


def test_relative_root_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rds = store.RobotDataStore("robot")

    rev = _within(5.0, rds.write_program, "r1", "p1", {"k": "v"}, base_rev=None)
    got = _within(5.0, rds.read_program, "r1", "p1")
    assert got.body == {"k": "v"}
    assert got.rev == rev
    assert _within(5.0, rds.list_programs, "r1") == ["p1"]
    assert (tmp_path / "robot" / "r1" / "programs" / "p1.yaml").read_bytes() == b"k: v\n"
    # документ с относительным root тоже читается/пишется
    r_doc = _within(5.0, rds.write, "r1", "params", {"a": 1}, base_rev=None)
    assert _within(5.0, rds.read, "r1", "params").rev == r_doc


# ---------------------------------------------------------------------------
# Битые файлы и некорректное тело
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "rev"),
    [
        (b": : :", "8b6a55b9c8a0694d26296a5af3555178ab178b6492112124c8139e23193227b6"),
        (b"- 1\n", "0b0d3d96d1b0b445467027cbb24e4f32df0ccca4ce1fda21fe57eb76dbaee808"),
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    ],
)
def test_broken_file_gives_invalid_with_rev_and_can_be_overwritten(rds, root: Path, raw: bytes, rev: str) -> None:
    path = root / "r1" / "params.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)

    with pytest.raises(errors.StoreDocumentInvalid) as ei:
        _within(5.0, rds.read, "r1", "params")
    assert ei.value.rev == rev
    assert str(ei.value) == "Файл данных робота не YAML-словарь"
    assert path.read_bytes() == raw  # чтение файл не трогает

    new_rev = _within(5.0, rds.write, "r1", "params", {"ok": 1}, base_rev=ei.value.rev)
    assert new_rev == _sha256(b"ok: 1\n")
    assert path.read_bytes() == b"ok: 1\n"


def test_broken_program_file_gives_invalid(rds, root: Path) -> None:
    path = root / "r1" / "programs" / "p1.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"- 1\n")
    with pytest.raises(errors.StoreDocumentInvalid) as ei:
        _within(5.0, rds.read_program, "r1", "p1")
    assert ei.value.rev == "0b0d3d96d1b0b445467027cbb24e4f32df0ccca4ce1fda21fe57eb76dbaee808"


@pytest.mark.parametrize("body", [[1], "text", None, {"x": object()}])
def test_bad_body_rejected_without_disk(rds, root: Path, tmp_path: Path, body) -> None:
    with pytest.raises(errors.StoreDocumentInvalid) as ei:
        _within(5.0, rds.write, "r1", "params", body, base_rev=None)
    assert ei.value.rev is None
    with pytest.raises(errors.StoreDocumentInvalid) as ei:
        _within(5.0, rds.write_program, "r1", "p1", body, base_rev=None)
    assert ei.value.rev is None
    assert list(tmp_path.iterdir()) == []


def test_bad_body_does_not_touch_existing_file(rds, root: Path) -> None:
    r0 = rds.write("r1", "params", {"v": 1}, base_rev=None)
    with pytest.raises(errors.StoreDocumentInvalid):
        _within(5.0, rds.write, "r1", "params", {"x": object()}, base_rev=r0)
    assert (root / "r1" / "params.yaml").read_bytes() == b"v: 1\n"
    assert [p.name for p in (root / "r1").iterdir()] == ["params.yaml"]


# ---------------------------------------------------------------------------
# Чтение и отказ не создают каталогов
# ---------------------------------------------------------------------------


def test_read_and_conflict_do_not_create_directories(rds, root: Path) -> None:
    assert _within(5.0, rds.read, "r9", "params") == store.StoredDoc(None, None)
    assert _within(5.0, rds.read_program, "r9", "p1") == store.StoredDoc(None, None)
    assert _within(5.0, rds.list_programs, "r9") == []
    with pytest.raises(errors.RevisionConflict):
        _within(5.0, rds.write, "r9", "params", {"v": 1}, base_rev="x")
    with pytest.raises(errors.RevisionConflict):
        _within(5.0, rds.write_program, "r9", "p1", {"v": 1}, base_rev="x")
    assert not root.exists()


# ---------------------------------------------------------------------------
# Содержимое и ревизия
# ---------------------------------------------------------------------------


def test_cyrillic_body_round_trip_without_loss(rds, root: Path) -> None:
    body = {"название": "Рисунок №1", "список": ["раз", "два"]}
    rev = _within(5.0, rds.write_program, "r1", "рисунок 1", body, base_rev=None)
    got = _within(5.0, rds.read_program, "r1", "рисунок 1")
    assert got.body == body
    assert got.rev == rev
    raw = (root / "r1" / "programs" / "рисунок 1.yaml").read_bytes()
    assert "Рисунок №1" in raw.decode("utf-8")  # allow_unicode: в файле буквы, а не \u-escape
    assert list(yaml.safe_load(raw)) == ["название", "список"]  # порядок ключей сохранён (sort_keys=False)


def test_compute_rev_literal() -> None:
    assert store.compute_rev(b"a: 1\n") == "37b128c59f1f5097f73f82691cb519f1f568667faab5ced1b4ab979d36837eae"


def test_write_returns_rev_of_file_bytes(rds, root: Path) -> None:
    rev = rds.write("r1", "frames", {"b": 2, "a": 1}, base_rev=None)
    raw = (root / "r1" / "frames.yaml").read_bytes()
    assert raw == b"b: 2\na: 1\n"
    assert rev == "2ada5f19bba7d27d756007d4a5ac25e066e05cc4bea25e1618e12165beae48b6"
    assert rds.read("r1", "frames").rev == rev
