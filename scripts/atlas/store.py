"""SQLite-хранилище реестра: сборки, узлы, рёбра, находки, снимки (Task 1.2, ADR-ATL-001 §5).

Purpose: одна строка `builds` на ключ (sha, main_ref, fingerprint); остальные таблицы — по build_id.
    Журнал по умолчанию (без WAL): повторная сборка с тем же ключом не меняет байты файла.
Public API: connect, find_build, write_build, read_build, build_row, modules_without_contract_test.
Stability: lite
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.atlas.schema import AdapterOutput, Edge, Finding, Node

__all__ = ["build_row", "connect", "find_build", "modules_without_contract_test", "read_build", "write_build"]

_DDL = """
CREATE TABLE IF NOT EXISTS builds (
    build_id INTEGER PRIMARY KEY, sha TEXT NOT NULL, main_ref TEXT NOT NULL, fingerprint TEXT NOT NULL,
    UNIQUE (sha, main_ref, fingerprint));
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
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Открыть (создав каталог и таблицы) базу реестра."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(_DDL)
    return con


def find_build(con: sqlite3.Connection, sha: str, main_ref: str, fingerprint: str) -> int | None:
    row = con.execute(
        "SELECT build_id FROM builds WHERE sha = ? AND main_ref = ? AND fingerprint = ?", (sha, main_ref, fingerprint)
    ).fetchone()
    return None if row is None else row[0]


def write_build(con: sqlite3.Connection, sha: str, main_ref: str, fingerprint: str, out: AdapterOutput) -> int:
    """Записать сборку одной транзакцией; ключ уже есть -> id существующей, ничего не пишется."""
    existing = find_build(con, sha, main_ref, fingerprint)
    if existing is not None:
        return existing
    with con:
        try:
            build_id = con.execute(
                "INSERT INTO builds (sha, main_ref, fingerprint) VALUES (?, ?, ?)", (sha, main_ref, fingerprint)
            ).lastrowid
        except sqlite3.IntegrityError:  # параллельная сборка записала тот же ключ раньше -> берём её id
            con.rollback()
            return find_build(con, sha, main_ref, fingerprint)  # type: ignore[return-value]
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
