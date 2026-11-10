"""Whitebox-тесты Task 4.5d: кэш атласа — оптимизация, а не условие работы; путь не в UTF-8 не роняет дерево.

Purpose: `store.connect` не бросает на мусорном файле (переименование в `.corrupt-*`), на каталоге кэша, который
    нельзя создать, на базе новее схемы (таблицы не стираются), на базе только для чтения со старой схемой и на
    базе под чужим `BEGIN EXCLUSIVE` (файл не переименовывается: `OperationalError` — подкласс `DatabaseError`);
    `ref --format passport` живёт без кэша; `Tree.files()` пропускает путь не в UTF-8. Дополняет слепые тесты
    `test_store_tree_blind_4_5d.py` проверкой ветвей, которых вслепую не видно (тип ошибки, порядок шагов).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы. «В памяти» проверяется по `PRAGMA database_list` (у `main` пустой путь файла).
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_SCHEMA = 5
_DEADLINE_S = 20.0  # sqlite3 ждёт блокировку 5 с по умолчанию


def _main_file(con: sqlite3.Connection) -> str:
    """Путь файла базы `main` у соединения; пусто — соединение в памяти."""
    return [row[2] for row in con.execute("PRAGMA database_list") if row[1] == "main"][0]


def _probe(path: Path) -> dict[str, Any]:
    """`store.connect(path)` в daemon-потоке; факты о соединении снимаются в том же потоке."""
    from scripts.atlas import store

    def call() -> dict[str, Any]:
        con = store.connect(path)
        try:
            return {
                "file": _main_file(con),
                "version": con.execute("PRAGMA user_version").fetchone()[0],
                "tables": {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")},
            }
        finally:
            con.close()

    return run_with_deadline(call, _DEADLINE_S)


def _make_db(path: Path, version: int) -> None:
    """База со схемой из `store._DDL`, одной строкой `nodes` (метка) и заданной `user_version`."""
    con = sqlite3.connect(path)
    try:
        con.executescript(
            "CREATE TABLE nodes (build_id INTEGER, kind TEXT, id TEXT, path TEXT, status TEXT, time INTEGER)"
        )
        con.execute("INSERT INTO nodes (build_id, kind, id) VALUES (1, 'marker', 'marker')")
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()
    finally:
        con.close()


def _marker_and_version(path: Path) -> tuple[int, int]:
    con = sqlite3.connect(path)
    try:
        return (
            con.execute("SELECT count(*) FROM nodes WHERE kind = 'marker'").fetchone()[0],
            con.execute("PRAGMA user_version").fetchone()[0],
        )
    finally:
        con.close()


def test_garbage_db_file_renamed_and_recreated(tmp_path: Path) -> None:
    path = tmp_path / "data" / "atlas.sqlite"
    path.parent.mkdir()
    path.write_text("garbage")

    facts = _probe(path)

    assert facts["file"].endswith("atlas.sqlite")  # на диске, не в памяти
    assert facts["version"] == _SCHEMA
    kept = [p for p in path.parent.iterdir() if ".corrupt-" in p.name]
    assert len(kept) == 1 and kept[0].read_text() == "garbage"
    assert path.is_file() and _marker_and_version(path)[1] == _SCHEMA


def test_unwritable_cache_path_works_in_memory(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("a file, not a directory")  # mkdir -> FileExistsError / NotADirectoryError

    facts = _probe(tmp_path / "data" / "atlas.sqlite")

    assert facts["file"] == ""
    assert facts["version"] == _SCHEMA
    assert {"builds", "scan_cache", "view_cache"} <= facts["tables"]
    assert [p.name for p in tmp_path.iterdir()] == ["data"]


def test_newer_schema_not_dropped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "atlas.sqlite"
    _make_db(path, _SCHEMA + 1)

    facts = _probe(path)

    assert facts["file"] == ""  # работа в памяти
    assert facts["version"] == 5  # у соединения в памяти — версия этого атласа, не файла
    assert _marker_and_version(path) == (1, _SCHEMA + 1)  # строки и версия на месте
    assert capsys.readouterr().err == "atlas: кэш новее этой версии атласа, работаю без кэша\n"


def test_ref_works_when_cache_unavailable(repo: GitRepo, atlas: Any) -> None:
    repo.write("pkg/__init__.py", "")
    repo.write("pkg/m.py", "def run():\n    return 1\n")
    repo.commit("fixture")
    (repo.path / "data").write_text("a file, not a directory")

    result = atlas(repo, "ref", "pkg/m.py::run", "--format", "passport", "--root", str(repo.path))

    assert result.code == 0, result.err
    assert any(line.startswith("== ") for line in result.out.splitlines()), result.out
    assert "atlas: кэш недоступен (" in result.err


def _commit_bad_path(repo: GitRepo) -> None:
    """Коммит с `ok.py` и путём `bad\xff.py` (на APFS файл с таким именем не создать: путь только в индексе)."""
    repo.write("ok.py", "x = 1\n")
    repo.commit("ok")
    blob = subprocess.run(
        ["git", "-C", str(repo.path), "hash-object", "-w", "--stdin"], input=b"y = 2\n", capture_output=True, check=True
    ).stdout.strip()
    subprocess.run(
        [
            b"git",
            b"-C",
            os.fsencode(repo.path),
            b"update-index",
            b"--add",
            b"--cacheinfo",
            b"100644," + blob + b",bad\xff.py",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo.path), "commit", "-q", "-m", "bad path"], check=True, capture_output=True)


def test_non_utf8_path_skipped(repo: GitRepo, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.atlas.tree import Tree

    _commit_bad_path(repo)
    capsys.readouterr()

    files = run_with_deadline(lambda: Tree(repo.path, repo.head).files())

    assert files == ["ok.py"]
    assert capsys.readouterr().err == "atlas: пропущено 1 путей не в UTF-8\n"


def test_git_z_is_strict_by_default_on_non_utf8_path(repo: GitRepo) -> None:
    """Пропуск включается только `skip_undecodable=True` в `Tree._ls`; прочие вызывающие (`check._renames` разбирает
    токены позиционно, пропуск сдвинул бы пары) получают `UnicodeDecodeError`, как раньше."""
    from scripts.atlas.tree import git_z

    _commit_bad_path(repo)

    with pytest.raises(UnicodeDecodeError):
        run_with_deadline(lambda: git_z(repo.path, "ls-tree", "-r", "-z", repo.head))


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset нет (Windows): пояс процесса не подменить")
def test_corrupt_stamp_is_utc_in_any_timezone(tmp_path: Path) -> None:
    path = tmp_path / "data" / "atlas.sqlite"
    path.parent.mkdir()
    path.write_text("garbage")
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC-9"  # POSIX-строка (без tzdata): UTC+9, локальное время на 9 часов впереди UTC
    time.tzset()
    try:
        before = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=2)
        _probe(path)
        after = datetime.now(timezone.utc) + timedelta(seconds=2)
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()

    kept = [p.name for p in path.parent.iterdir() if ".corrupt-" in p.name]
    assert len(kept) == 1, kept
    match = re.fullmatch(r"atlas\.sqlite\.corrupt-(\d{8}T\d{6})", kept[0])
    assert match, kept[0]
    stamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    assert before <= stamp <= after, (kept[0], before, after)


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="нет os.geteuid (Windows) или root: root пишет в файл 0o444, сценарий «только чтение» не воспроизвести",
)
def test_readonly_old_schema_db_works_in_memory(tmp_path: Path) -> None:
    path = tmp_path / "atlas.sqlite"
    _make_db(path, _SCHEMA - 1)
    path.chmod(0o444)
    try:
        facts = _probe(path)  # attempt to write a readonly database на шаге BEGIN IMMEDIATE/DROP, не бросает

        assert facts["file"] == ""
        assert facts["version"] == _SCHEMA
        assert _marker_and_version(path) == (1, _SCHEMA - 1)
    finally:
        path.chmod(0o644)


def test_locked_db_not_renamed(tmp_path: Path) -> None:
    path = tmp_path / "atlas.sqlite"
    _make_db(path, _SCHEMA)
    holder = sqlite3.connect(path, isolation_level=None)
    result: dict[str, Any] = {}
    try:
        holder.execute("BEGIN EXCLUSIVE")

        def call() -> None:
            try:
                result["facts"] = _probe_here(path)
            except BaseException as exc:  # noqa: BLE001 - отдаём в основной поток
                result["error"] = exc

        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        thread.join(_DEADLINE_S)  # ждёт таймаут sqlite3 по умолчанию (5 с)
        assert not thread.is_alive(), "connect завис под чужой блокировкой"
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert "error" not in result, repr(result.get("error"))
    assert result["facts"]["file"] == ""  # соединение в памяти
    assert [p.name for p in tmp_path.iterdir()] == ["atlas.sqlite"]  # на месте, `*.corrupt-*` нет
    assert _marker_and_version(path) == (1, _SCHEMA)


def _probe_here(path: Path) -> dict[str, Any]:
    from scripts.atlas import store

    con = store.connect(path)
    try:
        return {"file": _main_file(con)}
    finally:
        con.close()


# ---------------------------------------------------------------------- ревью r1: сохранение копии, гонка, усечение


def _connect_close(path: Path) -> None:
    from scripts.atlas import store

    store.connect(path).close()


def test_two_garbage_files_in_one_second_make_two_distinct_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.atlas import store

    monkeypatch.setattr(store, "_stamp", lambda: "20260101T000000")  # обе копии — в одну и ту же секунду
    path = tmp_path / "data" / "atlas.sqlite"
    path.parent.mkdir()
    path.write_bytes(b"garbage-ONE")
    _connect_close(path)
    first = capsys.readouterr().err
    path.unlink()  # базу заменили другим мусором
    path.write_bytes(b"garbage-TWO")
    _connect_close(path)
    second = capsys.readouterr().err

    copies = {p.name: p.read_bytes() for p in path.parent.iterdir() if ".corrupt-" in p.name}
    assert copies == {
        "atlas.sqlite.corrupt-20260101T000000": b"garbage-ONE",
        "atlas.sqlite.corrupt-20260101T000000-1": b"garbage-TWO",
    }
    assert first == "atlas: кэш повреждён, сохранён как atlas.sqlite.corrupt-20260101T000000\n"
    assert second == "atlas: кэш повреждён, сохранён как atlas.sqlite.corrupt-20260101T000000-1\n"


def test_healthy_db_swapped_in_after_garbage_seen_is_not_set_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Между «PRAGMA увидел мусор» и переносом другой процесс уже пересоздал базу: рабочая база остаётся на месте."""
    from scripts.atlas import store

    path = tmp_path / "atlas.sqlite"
    path.write_bytes(b"garbage")
    real = store._set_aside

    def swap_then_set_aside(target: Path) -> Path | None:
        target.unlink()
        _make_db(target, _SCHEMA)  # «другой процесс» пересоздал базу со строкой-меткой
        return real(target)

    monkeypatch.setattr(store, "_set_aside", swap_then_set_aside)

    facts = _probe(path)

    assert facts["file"].endswith("atlas.sqlite") and facts["version"] == _SCHEMA  # открыта на диске, не в памяти
    assert [p.name for p in tmp_path.iterdir()] == ["atlas.sqlite"]  # копий нет
    assert _marker_and_version(path) == (1, _SCHEMA)  # чужая рабочая база цела
    assert capsys.readouterr().err == ""


def test_garbage_removed_by_another_process_is_reopened_once_not_reported_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`FileNotFoundError` на переносе (другой процесс успел убрать мусор и создал базу): один повтор открытия."""
    from scripts.atlas import store

    path = tmp_path / "atlas.sqlite"
    path.write_bytes(b"garbage")

    def link_lost_race(src: Path, dst: Path) -> None:
        Path(src).unlink()
        _make_db(Path(src), _SCHEMA)
        raise FileNotFoundError(src)

    monkeypatch.setattr(store, "os", types.SimpleNamespace(link=link_lost_race))

    facts = _probe(path)

    assert facts["file"].endswith("atlas.sqlite") and facts["version"] == _SCHEMA
    assert [p.name for p in tmp_path.iterdir()] == ["atlas.sqlite"]
    assert capsys.readouterr().err == ""  # ни «недоступен», ни «повреждён»


def test_truncated_real_db_with_valid_signature_is_set_aside_and_recreated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Файл 17-98 байт с верной сигнатурой проходит `PRAGMA user_version` (версия 0), ломается на DDL."""
    path = tmp_path / "atlas.sqlite"
    _connect_close(path)  # настоящая база текущей схемы
    full = path.read_bytes()
    path.write_bytes(full[:50])

    facts = _probe(path)

    assert facts["file"].endswith("atlas.sqlite") and facts["version"] == _SCHEMA  # новая база на месте
    copies = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(copies) == 1 and copies[0].read_bytes() == full[:50]
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("atlas: кэш повреждён, сохранён как atlas.sqlite.corrupt-")


def test_passport_survives_scrambled_cache_page(repo: GitRepo, atlas: Any) -> None:
    """Версия в заголовке верная, страница 1 после 100-го байта забита: `get_scans`/`put_scans` — `DatabaseError`."""
    repo.write("pkg/__init__.py", "")
    repo.write("pkg/m.py", "def run():\n    return 1\n")
    repo.commit("fixture")
    db = repo.path / "data" / "atlas.sqlite"
    _connect_close(db)
    raw = bytearray(db.read_bytes())
    page_size = int.from_bytes(raw[16:18], "big")
    raw[100:page_size] = b"\xab" * (page_size - 100)
    db.write_bytes(bytes(raw))

    result = atlas(repo, "ref", "pkg/m.py::run", "--format", "passport", "--root", str(repo.path))

    assert result.code == 0, result.err
    assert any(line.startswith("== ") for line in result.out.splitlines()), result.out
