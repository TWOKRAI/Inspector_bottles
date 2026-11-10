"""Слепые приёмочные тесты Task 4.5d (RED до кода): кэш атласа — оптимизация, пути не в UTF-8 не роняют дерево.

Purpose: `store.connect(path)` не бросает на мусорном файле (A1), на каталоге кэша, который нельзя создать (A2),
    на базе новее схемы (A3), на базе только для чтения (A5), на базе под чужим `BEGIN EXCLUSIVE` (A6); регрессии
    пересоздания старой схемы и нетронутой текущей (A4); паспорт `ref --format passport` живёт без кэша (A7);
    `Tree.files()`/`oids()` не падают на пути не в UTF-8 (A8). Тесты написаны по критериям приёмки, без чтения
    замысла и без чтения реализации; ожидаемые значения — литералы.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Допущения (не описанные критериями детали): «в памяти» проверяется по `PRAGMA database_list` (у `main` пустой путь
файла); путь на диске читается отдельным соединением; сообщение А3 и сообщения А1/А2 — ровно одна строка stderr;
версия 6 готовится с таблицами и строками, как у живой базы схемы 5, но с `user_version = 6`.
"""

from __future__ import annotations

import builtins
import os
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_TABLES = {"builds", "nodes", "edges", "findings", "snapshots", "view_cache", "scan_cache"}
_SCHEMA = 5
_JOIN_DEADLINE_S = 20.0  # sqlite3 ждёт блокировку 5 с по умолчанию; с запасом

# схема 5 литералом (независимо от store._DDL): столбцы только для вставки строк в setup
_DDL = """
CREATE TABLE builds (build_id INTEGER PRIMARY KEY, sha TEXT NOT NULL, main_ref TEXT NOT NULL,
    fingerprint TEXT NOT NULL, base_tree TEXT NOT NULL DEFAULT '', UNIQUE (sha, main_ref, fingerprint, base_tree));
CREATE TABLE nodes (build_id INTEGER NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, path TEXT, status TEXT,
    time INTEGER, PRIMARY KEY (build_id, kind, id));
CREATE TABLE edges (build_id INTEGER NOT NULL, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
    via TEXT NOT NULL);
CREATE TABLE findings (build_id INTEGER NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL, node TEXT NOT NULL,
    detail TEXT NOT NULL, message TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE snapshots (build_id INTEGER NOT NULL, node TEXT NOT NULL, metric TEXT NOT NULL, value REAL,
    time INTEGER);
CREATE TABLE view_cache (sha TEXT NOT NULL, main_ref TEXT NOT NULL, adapters_fp TEXT NOT NULL, code TEXT NOT NULL,
    view TEXT NOT NULL, arg TEXT NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (sha, main_ref, adapters_fp, code, view, arg));
CREATE TABLE scan_cache (oid TEXT NOT NULL, scanner TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (oid, scanner));
"""


def _probe_con(con: sqlite3.Connection) -> dict[str, Any]:
    """Факты о соединении, снятые в том же потоке, где оно создано (sqlite3 не отдаёт соединение между потоками)."""
    main = [row for row in con.execute("PRAGMA database_list") if row[1] == "main"]
    facts: dict[str, Any] = {
        "memory": len(main) == 1 and main[0][2] == "",
        "version": con.execute("PRAGMA user_version").fetchone()[0],
        "tables": {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")},
    }
    if "builds" in facts["tables"] and "scan_cache" in facts["tables"]:
        facts["builds"] = con.execute("SELECT sha FROM builds").fetchall()
        facts["scans"] = con.execute("SELECT oid, scanner FROM scan_cache").fetchall()
        con.execute("INSERT INTO scan_cache VALUES ('probe-oid', 'probe-scanner', 'probe-body')")
        con.commit()  # запись и чтение работают
        facts["probe_row"] = con.execute(
            "SELECT body FROM scan_cache WHERE oid = 'probe-oid' AND scanner = 'probe-scanner'"
        ).fetchone()
    return facts


def _connect(path: Path, seconds: float = 60.0) -> dict[str, Any]:
    """`store.connect(path)` + факты о соединении в daemon-потоке с дедлайном; соединение закрывается там же.

    Импорт внутри: отсутствие кода — красный на тесте, не ошибка сбора.
    """

    return run_with_deadline(lambda: _connect_here(path), seconds)


def _connect_here(path: Path) -> dict[str, Any]:
    """То же в текущем потоке (вызывающий сам держит дедлайн)."""
    from scripts.atlas import store

    con = store.connect(path)
    try:
        return _probe_con(con)
    finally:
        con.close()


def _make_db(path: Path, version: int) -> None:
    """База с полной схемой, строкой в builds и в scan_cache и заданной `user_version`."""
    con = sqlite3.connect(path)
    try:
        con.executescript(_DDL)
        con.execute("INSERT INTO builds (sha, main_ref, fingerprint) VALUES ('abc123', 'main', 'fp')")
        con.execute("INSERT INTO scan_cache VALUES ('oid1', 'scanner1', '{}')")
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()
    finally:
        con.close()


def _disk(path: Path) -> tuple[int, set[str], int, int]:
    """(user_version, таблицы, строк в builds, строк в scan_cache) файла, отдельным соединением."""
    con = sqlite3.connect(path)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        builds = con.execute("SELECT count(*) FROM builds").fetchone()[0] if "builds" in tables else -1
        scans = con.execute("SELECT count(*) FROM scan_cache").fetchone()[0] if "scan_cache" in tables else -1
        return version, tables, builds, scans
    finally:
        con.close()


def _stderr_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().err.splitlines()


# ---------------------------------------------------------------------------------------------------------- A1


def _garbage_cache(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "atlas.sqlite"
    path.parent.mkdir()
    path.write_text("garbage")
    return path


def test_a1_garbage_file_connect_returns_working_disk_db_with_full_schema(tmp_path, capsys):
    path = _garbage_cache(tmp_path)

    facts = _connect(path)

    assert facts["tables"] >= _TABLES
    assert facts["version"] == _SCHEMA
    assert facts["memory"] is False  # на месте path — свежая рабочая база, а не память
    assert facts["probe_row"] == ("probe-body",)
    version, tables, builds, scans = _disk(path)  # запись дошла до файла по path
    assert (version, builds, scans) == (_SCHEMA, 0, 1)
    assert tables >= _TABLES


def test_a1_garbage_file_is_kept_aside_as_single_corrupt_copy_with_utc_timestamp(tmp_path, capsys):
    path = _garbage_cache(tmp_path)
    before = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=2)

    _connect(path)
    after = datetime.now(timezone.utc) + timedelta(seconds=2)

    aside = sorted(p for p in path.parent.iterdir() if p.name != "atlas.sqlite")
    assert len(aside) == 1, [p.name for p in aside]
    match = re.fullmatch(r"atlas\.sqlite\.corrupt-(\d{8}T\d{6})", aside[0].name)
    assert match, aside[0].name
    stamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    assert before <= stamp <= after  # метка — UTC, момент вызова
    assert aside[0].read_bytes() == b"garbage"  # прежнее содержимое, байт в байт


def test_a1_garbage_file_reports_exactly_one_stderr_line_naming_the_copy(tmp_path, capsys):
    path = _garbage_cache(tmp_path)

    _connect(path)

    lines = _stderr_lines(capsys)
    assert len(lines) == 1, lines
    assert lines[0].startswith("atlas: кэш повреждён, сохранён как ")
    aside = [p.name for p in path.parent.iterdir() if ".corrupt-" in p.name]
    assert len(aside) == 1 and aside[0] in lines[0]


# ---------------------------------------------------------------------------------------------------------- A2


def _blocked_path(tmp_path: Path) -> Path:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    return blocker / "atlas.sqlite"  # родитель — обычный файл: каталог кэша не создать даже под root


def test_a2_uncreatable_cache_dir_returns_working_in_memory_db_with_full_schema(tmp_path, capsys):
    facts = _connect(_blocked_path(tmp_path))  # не бросает

    assert facts["memory"] is True
    assert facts["tables"] >= _TABLES
    assert facts["version"] == _SCHEMA
    assert facts["probe_row"] == ("probe-body",)  # запись и чтение работают


def test_a2_uncreatable_cache_dir_creates_nothing_on_disk(tmp_path, capsys):
    _connect(_blocked_path(tmp_path))

    assert [p.name for p in tmp_path.iterdir()] == ["blocker"]
    assert (tmp_path / "blocker").is_file() and (tmp_path / "blocker").read_text() == "not a directory"


def test_a2_uncreatable_cache_dir_reports_one_stderr_line_with_error_class_name(tmp_path, capsys):
    _connect(_blocked_path(tmp_path))

    lines = _stderr_lines(capsys)
    assert len(lines) == 1, lines
    match = re.fullmatch(r"atlas: кэш недоступен \((\w+)\), работаю без кэша", lines[0])
    assert match, lines[0]
    cls = getattr(builtins, match.group(1), None) or getattr(sqlite3, match.group(1), None)
    assert isinstance(cls, type) and issubclass(cls, Exception), match.group(1)  # имя класса ошибки, не слово


# ---------------------------------------------------------------------------------------------------------- A3


def test_a3_newer_schema_is_not_wiped_on_disk(tmp_path, capsys):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, 6)

    _connect(path)

    version, tables, builds, scans = _disk(path)
    assert version == 6  # не пересоздана и не понижена
    assert tables >= _TABLES
    assert (builds, scans) == (1, 1)  # строки на месте, проба в файл не писала


def test_a3_newer_schema_returns_working_in_memory_db_of_current_schema(tmp_path, capsys):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, 6)

    facts = _connect(path)

    assert facts["memory"] is True
    assert facts["version"] == _SCHEMA
    assert facts["tables"] >= _TABLES
    assert facts["probe_row"] == ("probe-body",)


def test_a3_newer_schema_reports_exactly_one_stderr_line(tmp_path, capsys):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, 6)

    _connect(path)

    assert _stderr_lines(capsys) == ["atlas: кэш новее этой версии атласа, работаю без кэша"]


# ---------------------------------------------------------------------------------------------------------- A4


def test_a4_older_schema_is_recreated_as_before(tmp_path, capsys):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, 4)

    facts = _connect(path)

    assert facts["version"] == _SCHEMA
    assert (facts["builds"], facts["scans"]) == ([], [])  # старые строки стёрты
    assert facts["memory"] is False
    version, tables, builds, scans = _disk(path)
    assert (version, builds, scans) == (_SCHEMA, 0, 1)  # на диске только строка пробы
    assert tables >= _TABLES
    assert [p.name for p in tmp_path.iterdir()] == ["atlas.sqlite"]  # старая база не откладывается как битая


def test_a4_current_schema_keeps_data_and_is_silent(tmp_path, capsys):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, _SCHEMA)

    facts = _connect(path)

    assert facts["memory"] is False
    assert facts["builds"] == [("abc123",)]
    assert facts["scans"] == [("oid1", "scanner1")]
    assert _disk(path)[0] == _SCHEMA
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------------------------------------- A5


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root пишет в файл с правами 0o444: сценарий «только чтение» не воспроизвести"
)
def test_a5_read_only_old_schema_db_returns_working_in_memory_db(tmp_path, capsys):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, 4)
    path.chmod(0o444)
    try:
        facts = _connect(path)

        assert facts["memory"] is True
        assert facts["version"] == _SCHEMA
        assert facts["tables"] >= _TABLES
        assert facts["probe_row"] == ("probe-body",)
        assert _disk(path)[:1] == (4,)  # файл только для чтения остался как был
        assert [p.name for p in tmp_path.iterdir()] == ["atlas.sqlite"]
    finally:
        path.chmod(0o644)


# ---------------------------------------------------------------------------------------------------------- A6


@pytest.mark.parametrize("version", [5, 4])
def test_a6_exclusively_locked_healthy_db_is_kept_and_memory_db_returned(tmp_path, capsys, version):
    path = tmp_path / "atlas.sqlite"
    _make_db(path, version)
    holder = sqlite3.connect(path, isolation_level=None)
    result: dict[str, Any] = {}
    try:
        holder.execute("BEGIN EXCLUSIVE")

        def call() -> None:
            try:
                result["facts"] = _connect_here(path)
            except BaseException as exc:  # noqa: BLE001 - отдаём в основной поток
                result["error"] = exc

        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        thread.join(_JOIN_DEADLINE_S)
        assert not thread.is_alive(), "connect завис под чужой блокировкой"
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert "error" not in result, repr(result.get("error"))
    facts = result["facts"]
    assert facts["memory"] is True
    assert facts["version"] == _SCHEMA
    assert facts["probe_row"] == ("probe-body",)
    assert [p.name for p in tmp_path.iterdir()] == ["atlas.sqlite"]  # на месте, никаких *.corrupt-*
    assert _disk(path)[0] == version and _disk(path)[2:] == (1, 1)  # не пересоздан, проба в файл не писала


# ---------------------------------------------------------------------------------------------------------- A7


def _passport_repo(repo: GitRepo) -> None:
    repo.write("pkg/__init__.py", "")
    repo.write("pkg/m.py", "def run():\n    return 1\n")
    repo.commit("fixture")


def _passport(atlas: Any, repo: GitRepo) -> Any:
    return atlas(repo, "ref", "pkg/m.py::run", "--format", "passport", "--root", str(repo.path))


def test_a7_passport_without_reachable_cache_dir_exits_zero_and_prints_passport(repo: GitRepo, atlas: Any) -> None:
    _passport_repo(repo)
    (repo.path / "data").write_text("data is a file, not a directory")  # data/atlas.sqlite создать нельзя

    result = _passport(atlas, repo)

    assert result.code == 0, result.err
    assert any(line.startswith("== ") for line in result.out.splitlines()), result.out
    assert any(line.startswith("atlas: кэш недоступен (") for line in result.err.splitlines()), result.err


def test_a7_passport_without_cache_equals_passport_with_cache(repo: GitRepo, atlas: Any) -> None:
    _passport_repo(repo)
    baseline = _passport(atlas, repo)  # обычный прогон, кэш создаётся
    assert baseline.code == 0, baseline.err
    assert (repo.path / "data" / "atlas.sqlite").is_file()
    for child in (repo.path / "data").iterdir():
        child.unlink()
    (repo.path / "data").rmdir()
    (repo.path / "data").write_text("data is a file, not a directory")

    degraded = _passport(atlas, repo)

    assert degraded.code == 0, degraded.err
    assert degraded.out == baseline.out  # кэш — оптимизация: вывод тот же


def test_a7_passport_with_garbage_cache_file_exits_zero_and_keeps_copy(repo: GitRepo, atlas: Any) -> None:
    _passport_repo(repo)
    (repo.path / "data").mkdir()
    (repo.path / "data" / "atlas.sqlite").write_text("garbage")

    result = _passport(atlas, repo)

    assert result.code == 0, result.err
    assert any(line.startswith("== ") for line in result.out.splitlines()), result.out
    aside = [p for p in (repo.path / "data").iterdir() if p.name.startswith("atlas.sqlite.corrupt-")]
    assert len(aside) == 1, [p.name for p in (repo.path / "data").iterdir()]
    assert aside[0].read_bytes() == b"garbage"
    assert any(line.startswith("atlas: кэш повреждён, сохранён как ") for line in result.err.splitlines()), result.err


# ---------------------------------------------------------------------------------------------------------- A8


def _git_bytes(root: Path, *args: bytes, input: bytes | None = None) -> bytes:
    proc = subprocess.run(
        [b"git", b"-C", os.fsencode(root), *args], input=input, capture_output=True, check=False, timeout=60
    )
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout


def _commit_with_index_only_paths(repo: GitRepo, bad_paths: list[bytes]) -> str:
    """Коммит с `ok.py` и записями индекса, чьи пути — байты (файл с таким именем на APFS не создать)."""
    repo.write("ok.py", "x = 1\n")
    repo.commit("ok")
    blob = _git_bytes(repo.path, b"hash-object", b"-w", b"--stdin", input=b"y = 2\n").strip()
    for name in bad_paths:
        _git_bytes(repo.path, b"update-index", b"--add", b"--cacheinfo", b"100644," + blob + b"," + name)
    _git_bytes(repo.path, b"commit", b"-q", b"-m", b"bad paths")
    listing = _git_bytes(repo.path, b"ls-tree", b"-r", b"-z", b"HEAD")
    for name in bad_paths:  # страховка setup: запись правда лежит в дереве коммита
        assert b"\t" + name + b"\0" in listing, listing
    return repo.head


def test_a8_files_skips_non_utf8_path_and_keeps_good_one(repo: GitRepo, capsys) -> None:
    from scripts.atlas.tree import Tree

    sha = _commit_with_index_only_paths(repo, [b"bad\xff.py"])
    capsys.readouterr()

    files = run_with_deadline(lambda: Tree(repo.path, sha).files())

    assert files == ["ok.py"]  # не UnicodeDecodeError, битый путь не просочился даже с заменой символа


def test_a8_oids_skips_non_utf8_path_too(repo: GitRepo, capsys) -> None:
    from scripts.atlas.tree import Tree

    sha = _commit_with_index_only_paths(repo, [b"bad\xff.py"])
    capsys.readouterr()

    oids = run_with_deadline(lambda: Tree(repo.path, sha).oids())

    assert list(oids) == ["ok.py"]


def test_a8_non_utf8_path_reports_exactly_one_stderr_line_even_after_files_and_oids(repo: GitRepo, capsys) -> None:
    from scripts.atlas.tree import Tree

    sha = _commit_with_index_only_paths(repo, [b"bad\xff.py"])
    capsys.readouterr()
    tree = Tree(repo.path, sha)

    run_with_deadline(lambda: (tree.files(), tree.oids()))

    assert _stderr_lines(capsys) == ["atlas: пропущено 1 путей не в UTF-8"]


def test_a8_skipped_count_is_the_number_of_non_utf8_paths(repo: GitRepo, capsys) -> None:
    from scripts.atlas.tree import Tree

    sha = _commit_with_index_only_paths(repo, [b"bad\xff.py", b"dir/\xfe\xfdworse.py"])
    capsys.readouterr()

    files = run_with_deadline(lambda: Tree(repo.path, sha).files())

    assert files == ["ok.py"]
    assert _stderr_lines(capsys) == ["atlas: пропущено 2 путей не в UTF-8"]


def test_a8_tree_without_non_utf8_paths_is_silent_and_complete(repo: GitRepo, capsys) -> None:
    from scripts.atlas.tree import Tree

    repo.write("ok.py", "x = 1\n")
    repo.write("sub/déjà.py", "z = 3\n")  # настоящий UTF-8, не повод пропускать
    sha = repo.commit("good")
    capsys.readouterr()

    files = run_with_deadline(lambda: Tree(repo.path, sha).files())

    assert sorted(files) == ["ok.py", "sub/déjà.py"]
    assert "не в UTF-8" not in capsys.readouterr().err
