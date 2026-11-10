"""SQLite-хранилище реестра: сборки, узлы, рёбра, находки, снимки (Task 1.2, ADR-ATL-001 §5).

Purpose: одна строка `builds` на ключ (sha, main_ref, fingerprint, base_tree); остальные таблицы — по build_id.
    Журнал по умолчанию (без WAL): повторная сборка с тем же ключом не меняет байты файла.
Public API: connect, find_build, write_build, read_build, build_row, modules_without_contract_test, get_view, put_view,
    get_scans, put_scans.
    Таблица view_cache — готовый вывод `ref`/`card` (список строк) по ключу ревизии, отпечатков адаптеров и кода.
    Таблица scan_cache — факты файла (JSON) по oid блоба и ключу сканера (scripts.atlas.scan.SCANNER).
Stability: lite
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from scripts.atlas.schema import AdapterOutput, Edge, Finding, Node

__all__ = [
    "build_row",
    "connect",
    "find_build",
    "get_scans",
    "get_view",
    "modules_without_contract_test",
    "put_scans",
    "put_view",
    "read_build",
    "write_build",
]

_DDL = """
CREATE TABLE IF NOT EXISTS builds (
    build_id INTEGER PRIMARY KEY, sha TEXT NOT NULL, main_ref TEXT NOT NULL, fingerprint TEXT NOT NULL,
    base_tree TEXT NOT NULL DEFAULT '', UNIQUE (sha, main_ref, fingerprint, base_tree));
CREATE TABLE IF NOT EXISTS nodes (
    build_id INTEGER NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, path TEXT, status TEXT, time INTEGER,
    PRIMARY KEY (build_id, kind, id));
CREATE TABLE IF NOT EXISTS edges (
    build_id INTEGER NOT NULL, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL, via TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS edges_kind_dst ON edges (build_id, kind, dst);
CREATE TABLE IF NOT EXISTS findings (
    build_id INTEGER NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL, node TEXT NOT NULL,
    detail TEXT NOT NULL, message TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
    build_id INTEGER NOT NULL, node TEXT NOT NULL, metric TEXT NOT NULL, value REAL, time INTEGER);
CREATE TABLE IF NOT EXISTS view_cache (
    sha TEXT NOT NULL, main_ref TEXT NOT NULL, adapters_fp TEXT NOT NULL, code TEXT NOT NULL, view TEXT NOT NULL,
    arg TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (sha, main_ref, adapters_fp, code, view, arg));
CREATE TABLE IF NOT EXISTS scan_cache (
    oid TEXT NOT NULL, scanner TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (oid, scanner));
"""
_SCHEMA = 5  # PRAGMA user_version; база — производный кэш: версия ниже -> таблицы пересоздаются, выше -> не трогается
_TABLES = ("builds", "nodes", "edges", "findings", "snapshots", "view_cache", "scan_cache")


class _NotADatabase(Exception):
    """Файл по пути — не база SQLite (`DatabaseError`, не `OperationalError`, на первом `PRAGMA`)."""


class _NewerSchema(Exception):
    """`user_version` файла выше `_SCHEMA`: база новее этой версии атласа, её таблицы не стираются."""


def _create_schema(con: sqlite3.Connection) -> None:
    for statement in filter(str.strip, _DDL.split(";")):  # executescript сам делает COMMIT
        con.execute(statement)
    con.execute(f"PRAGMA user_version = {_SCHEMA}")


def _open(path: str | Path) -> sqlite3.Connection:
    """Открыть базу по `path` (каталог и таблицы создаются; версия ниже `_SCHEMA` -> пересоздание в файле)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    try:
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.OperationalError:  # `database is locked`, `unable to open database file`: файл здоров
            raise
        except sqlite3.DatabaseError as exc:  # `file is not a database`
            raise _NotADatabase from exc
        if version > _SCHEMA:
            raise _NewerSchema
        if version != _SCHEMA:
            try:
                con.execute("BEGIN IMMEDIATE")
                if con.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA:  # другой процесс мог успеть раньше
                    for table in _TABLES:
                        con.execute(f"DROP TABLE IF EXISTS {table}")
                    _create_schema(con)
                con.execute("COMMIT")
            except sqlite3.OperationalError:  # только для чтения, занята: файл здоров
                raise
            except (
                sqlite3.DatabaseError
            ) as exc:  # усечённый файл с верной сигнатурой: `database disk image is malformed`
                raise _NotADatabase from exc
    except BaseException:
        con.close()
        raise
    con.isolation_level = ""  # дальше — обычный режим транзакций, как у остального кода
    return con


def _in_memory(message: str) -> sqlite3.Connection:
    """Соединение «в памяти» с той же схемой и строка в stderr: кэш — оптимизация, а не условие работы."""
    print(message, file=sys.stderr)
    con = sqlite3.connect(":memory:", isolation_level=None)
    _create_schema(con)
    con.isolation_level = ""
    return con


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _is_not_a_database(path: Path) -> bool:
    """Файл по `path` и сейчас не база? Читает заново, только на чтение: файла нет или он здоров -> False."""
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()  # и сигнатура, и первая страница
    except sqlite3.OperationalError:
        return False
    except sqlite3.DatabaseError:
        return True
    finally:
        con.close()
    return False


def _set_aside(path: Path) -> Path | None:
    """Перенести не-базу в `<имя>.corrupt-<UTC YYYYmmddTHHMMSS>[-N]` рядом; вернуть имя копии.

    Файл перечитывается: другой процесс мог уже пересоздать базу -> None, файл не трогается. Занятость имени копии
    проверяет `os.link` (FileExistsError -> следующий суффикс `-1`, `-2`, …): `rename` перезаписал бы чужую копию.
    `FileNotFoundError` (другой процесс успел убрать файл) и прочие `OSError` — наверх.
    """
    if not _is_not_a_database(path):
        return None
    stamp = _stamp()
    for n in itertools.count():
        target = path.with_name(f"{path.name}.corrupt-{stamp}" + (f"-{n}" if n else ""))
        try:
            os.link(path, target)
        except FileExistsError:
            continue
        break
    try:
        path.unlink()
    except FileNotFoundError:  # другой процесс убрал файл между link и unlink: копия сохранена
        pass
    return target


def connect(path: str | Path) -> sqlite3.Connection:
    """Открыть (создав каталог и таблицы) базу реестра; отказ кэша не бросает, а даёт базу в памяти.

    Версия ниже `_SCHEMA` -> таблицы пересоздаются (сброс — одна транзакция IMMEDIATE, файл не удаляется:
    параллельный `atlas build` держит его открытым). Версия выше -> таблицы не стираются, работа в памяти.
    Файл — не база (мусор, усечённый файл) -> сохраняется копией `<имя>.corrupt-<UTC>[-N]`, база создаётся заново (если
    другой процесс уже пересоздал её — файл не трогается). Любая другая
    `sqlite3.Error`/`OSError` (каталог не создать, база занята или только для чтения) -> база в памяти и строка
    в stderr; файл не трогается. Вызывающий отличить соединение «в памяти» не может и не должен.
    """
    path = Path(path)
    try:
        try:
            return _open(path)
        except _NotADatabase:
            try:
                kept = _set_aside(path)
            except FileNotFoundError:  # другой процесс убрал мусор раньше нас: файла нет, база создастся заново
                kept = None
            if kept is not None:
                print(f"atlas: кэш повреждён, сохранён как {kept.name}", file=sys.stderr)
            return _open(path)  # один повтор: файл уже пересоздан (нами или другим процессом)
    except _NewerSchema:
        return _in_memory("atlas: кэш новее этой версии атласа, работаю без кэша")
    except (sqlite3.Error, OSError, _NotADatabase) as exc:  # `_NotADatabase` — и после переименования
        real = exc.__cause__ if isinstance(exc, _NotADatabase) else exc
        return _in_memory(f"atlas: кэш недоступен ({type(real).__name__}), работаю без кэша")


def find_build(con: sqlite3.Connection, sha: str, main_ref: str, fingerprint: str, base_tree: str = "") -> int | None:
    row = con.execute(
        "SELECT build_id FROM builds WHERE sha = ? AND main_ref = ? AND fingerprint = ? AND base_tree = ?",
        (sha, main_ref, fingerprint, base_tree),
    ).fetchone()
    return None if row is None else row[0]


def write_build(
    con: sqlite3.Connection, sha: str, main_ref: str, fingerprint: str, out: AdapterOutput, base_tree: str = ""
) -> int:
    """Записать сборку одной транзакцией; ключ уже есть -> id существующей, ничего не пишется."""
    existing = find_build(con, sha, main_ref, fingerprint, base_tree)
    if existing is not None:
        return existing
    with con:
        try:
            build_id = con.execute(
                "INSERT INTO builds (sha, main_ref, fingerprint, base_tree) VALUES (?, ?, ?, ?)",
                (sha, main_ref, fingerprint, base_tree),
            ).lastrowid
        except sqlite3.IntegrityError:  # параллельная сборка записала тот же ключ раньше -> берём её id
            con.rollback()
            return find_build(con, sha, main_ref, fingerprint, base_tree)  # type: ignore[return-value]
        con.executemany(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?)",
            [(build_id, n.kind, n.id, n.path, n.status, n.time) for n in out.nodes],
        )
        con.executemany(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?)", [(build_id, e.kind, e.src, e.dst, e.via) for e in out.edges]
        )
        con.executemany(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(build_id, f.code, f.severity, f.node, f.detail, f.message, f.source) for f in out.findings],
        )
    return build_id


def build_row(con: sqlite3.Connection, build_id: int) -> tuple[str, str]:
    """(sha, main_ref) сборки."""
    return con.execute("SELECT sha, main_ref FROM builds WHERE build_id = ?", (build_id,)).fetchone()


def read_build(con: sqlite3.Connection, build_id: int) -> AdapterOutput:
    """Содержимое сборки в порядке, не гарантированном: сортирует потребитель."""
    q = "SELECT {} FROM {} WHERE build_id = ?"
    return AdapterOutput(
        nodes=[Node(*r) for r in con.execute(q.format("kind, id, path, status, time", "nodes"), (build_id,))],
        edges=[Edge(*r) for r in con.execute(q.format("kind, src, dst, via", "edges"), (build_id,))],
        findings=[
            Finding(*r)
            for r in con.execute(q.format("code, severity, node, detail, message, source", "findings"), (build_id,))
        ],
    )


def modules_without_contract_test(con: sqlite3.Connection, build_id: int, since_ts: int) -> list[str]:
    """Модули, тронутые коммитами с time >= since_ts, без теста в каталоге `tests/contract/`, по возрастанию id."""
    rows = con.execute(
        """
        SELECT DISTINCT substr(e.dst, 8) AS module FROM edges e
        JOIN nodes c ON c.build_id = e.build_id AND c.kind = 'commit' AND c.id = substr(e.src, 8)
        JOIN nodes m ON m.build_id = e.build_id AND m.kind = 'module' AND m.id = substr(e.dst, 8)
        WHERE e.build_id = ? AND e.kind = 'touches' AND c.time >= ?
          AND NOT EXISTS (
            SELECT 1 FROM edges t
            JOIN nodes n ON n.build_id = t.build_id AND n.kind = 'test' AND n.id = substr(t.src, 6)
            WHERE t.build_id = e.build_id AND t.kind = 'tests' AND t.dst = e.dst
              AND instr(n.path, '/tests/contract/') > 0)
        ORDER BY module
        """,
        (build_id, since_ts),
    )
    return [r[0] for r in rows]


def get_view(
    con: sqlite3.Connection, sha: str, main_ref: str, fingerprint: str, code: str, view: str, arg: str
) -> list[str] | None:
    """Готовые строки вида по полному ключу или None; `code` — отпечаток исходников atlas."""
    row = con.execute(
        "SELECT body FROM view_cache WHERE sha = ? AND main_ref = ? AND adapters_fp = ? AND code = ? "
        "AND view = ? AND arg = ?",
        (sha, main_ref, fingerprint, code, view, arg),
    ).fetchone()
    if row is None:
        return None
    try:
        lines = json.loads(row[0])
    except ValueError:  # битая строка кэша — промах, put_view её перезапишет
        return None
    return lines if isinstance(lines, list) and all(isinstance(x, str) for x in lines) else None


def put_view(
    con: sqlite3.Connection, sha: str, main_ref: str, fingerprint: str, code: str, view: str, arg: str, lines: list[str]
) -> None:
    """Запомнить строки вида (только успешный результат); тот же ключ перезаписывается."""
    try:
        with con:
            con.execute(
                "INSERT OR REPLACE INTO view_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sha, main_ref, fingerprint, code, view, arg, json.dumps(lines, ensure_ascii=False)),
            )
    except sqlite3.OperationalError as exc:  # база занята читателем: кэш — оптимизация, вид уже посчитан
        print(f"atlas: кэш вида не записан: {exc}", file=sys.stderr)


_CHUNK = 500  # предел переменных в одном `IN (...)`


def get_scans(con: sqlite3.Connection, scanner: str, oids: Iterable[str]) -> dict[str, str]:
    """Тела фактов (`FileFacts.to_json()`) по oid для ключа `scanner`; форму не проверяет — это дело `scan`.

    База занята или повреждена -> строка в stderr и {} (все промахи): кэш — оптимизация.
    """
    wanted = list(dict.fromkeys(oids))
    found: dict[str, str] = {}
    try:
        for i in range(0, len(wanted), _CHUNK):
            chunk = wanted[i : i + _CHUNK]
            marks = ", ".join("?" * len(chunk))
            sql = f"SELECT oid, body FROM scan_cache WHERE scanner = ? AND oid IN ({marks})"
            found.update(con.execute(sql, (scanner, *chunk)))
    except sqlite3.DatabaseError as exc:  # занята (OperationalError) или страницы повреждены: все промахи
        print(f"atlas: кэш фактов не прочитан: {exc}", file=sys.stderr)
        return {}
    return found


def put_scans(con: sqlite3.Connection, scanner: str, rows: Iterable[tuple[str, str]]) -> None:
    """Записать пары (oid, body) одной транзакцией; тот же ключ перезаписывается."""
    try:
        with con:
            con.executemany(
                "INSERT OR REPLACE INTO scan_cache (oid, scanner, body) VALUES (?, ?, ?)",
                [(oid, scanner, body) for oid, body in rows],
            )
    except sqlite3.DatabaseError as exc:  # база занята читателем или повреждена: факты уже разобраны
        print(f"atlas: кэш фактов не записан: {exc}", file=sys.stderr)
