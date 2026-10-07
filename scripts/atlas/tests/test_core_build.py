"""Приёмочные тесты сборки ядра scripts/atlas: build, кэш, --json (Task 1.2, RED).

Purpose: слепые тесты (REDS 1-3, 6) по DESIGN брифа 1.2 и ADR-ATL-001/002:
    одна строка сборки, кэш по ключу (sha, main_ref, отпечаток адаптеров),
    детерминированный и упорядоченный --json.
Public API: нет (только test_*).
Stability: lite
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

__all__: list[str] = []


def _builds_rows(db_path):
    """Строки таблицы сборок: таблица с колонками sha, main_ref, fingerprint (сигнатура write_build)."""
    con = sqlite3.connect(db_path)
    try:
        found = []
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
            if {"sha", "main_ref", "fingerprint"} <= set(cols):
                found.append(table)
        assert len(found) == 1, f"нужна ровно одна таблица сборок (sha, main_ref, fingerprint); есть: {tables}"
        return con.execute(f'SELECT sha, main_ref, fingerprint FROM "{found[0]}"').fetchall()
    finally:
        con.close()


def test_build_on_repo_with_plans_and_docs_exits_0_with_one_build_row(repo, atlas, set_adapters):
    repo.write("plans/2026-10-04_demo/plan.md", "# plan\n")
    repo.write("docs/readme.md", "# readme\n")
    sha = repo.commit("init")
    set_adapters()

    result = atlas(repo, "build", cwd=repo.path / "docs")  # корень — git toplevel, не cwd

    assert result.code == 0, result.err
    db_path = repo.path / "data" / "atlas.sqlite"
    assert db_path.is_file()
    assert not (repo.path / "docs" / "data").exists()
    rows = _builds_rows(db_path)
    assert [(r[0], r[1]) for r in rows] == [(sha, "main")]


def test_rebuild_same_key_calls_no_adapter_and_leaves_db_bytes_unchanged(repo, atlas, set_adapters):
    from scripts.atlas.tests.conftest import CountingAdapter

    repo.write("docs/readme.md", "# readme\n")
    repo.commit("init")
    counter = CountingAdapter()
    set_adapters(counter)
    db_path = repo.path / "data" / "atlas.sqlite"

    first = atlas(repo, "build")
    assert first.code == 0, first.err
    assert counter.calls == 1
    digest_before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    second = atlas(repo, "build")

    assert second.code == 0, second.err
    assert counter.calls == 1, "второй build с тем же ключом не должен звать collect()"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == digest_before


def test_json_is_byte_identical_and_ordered(repo, atlas, set_adapters):
    from scripts.atlas.schema import AdapterOutput, Edge, Finding, Node
    from scripts.atlas.tests.conftest import FixedAdapter

    def factory():
        # всё подано в обратном порядке относительно ожидаемой сортировки
        nodes = [
            Node(kind="plan", id="p", path="plans/p/plan.md", status=None, time=None),
            Node(kind="module", id="b", path="modules/b", status=None, time=None),
            Node(kind="module", id="a", path="modules/a", status=None, time=None),
            Node(kind="doc", id="docs/дока.md", path="docs/дока.md", status="fresh", time=None),
            Node(kind="commit", id="ccc2", path=None, status=None, time=200),
            Node(kind="commit", id="ccc1", path=None, status=None, time=100),
        ]
        edges = [
            Edge(kind="touches", src="commit:ccc2", dst="module:a", via="path"),
            Edge(kind="touches", src="commit:ccc1", dst="module:b", via="path"),
            Edge(kind="touches", src="commit:ccc1", dst="module:a", via="table"),
            Edge(kind="touches", src="commit:ccc1", dst="module:a", via="path"),
            Edge(kind="refs", src="commit:ccc1", dst="plan:p", via="trailer:Refs"),
            Edge(kind="covers", src="doc:docs/дока.md", dst="module:a", via="table"),
        ]
        findings = [
            Finding(code="REF_MOVED", severity="info", node="commit:ccc1", detail="", message="m", source="s"),
            Finding(
                code="BROKEN_LINK", severity="blocking", node="doc:docs/дока.md", detail="y.md", message="m", source="s"
            ),
            Finding(
                code="BROKEN_LINK", severity="blocking", node="doc:docs/дока.md", detail="x.md", message="m", source="s"
            ),
            Finding(
                code="BROKEN_LINK", severity="blocking", node="commit:ccc1", detail="z.md", message="m", source="s"
            ),
        ]
        return AdapterOutput(nodes=nodes, edges=edges, findings=findings)

    repo.write("docs/readme.md", "# readme\n")
    sha = repo.commit("init")
    set_adapters(FixedAdapter(factory))
    db_path = repo.path / "data" / "atlas.sqlite"

    first = atlas(repo, "--json")
    second = atlas(repo, "--json")  # из кэша
    db_path.unlink()
    third = atlas(repo, "--json")  # пересборка с нуля

    assert first.code == 0, first.err
    assert second.out == first.out
    assert third.out == first.out
    assert "дока" in first.out and "\\u0434" not in first.out, "ensure_ascii=False"
    data = json.loads(first.out)
    assert list(data.keys()) == [
        "schema_version",
        "head",
        "main_ref",
        "legacy_before",
        "nodes",
        "edges",
        "findings",
        "plans",
    ]
    assert data["schema_version"] == 1
    assert data["head"] == sha
    assert data["main_ref"] == "main"
    assert data["legacy_before"] is None
    assert data["plans"] is None
    assert data["nodes"] == [
        {"kind": "commit", "id": "ccc1", "path": None, "status": None, "time": 100},
        {"kind": "commit", "id": "ccc2", "path": None, "status": None, "time": 200},
        {"kind": "doc", "id": "docs/дока.md", "path": "docs/дока.md", "status": "fresh", "time": None},
        {"kind": "module", "id": "a", "path": "modules/a", "status": None, "time": None},
        {"kind": "module", "id": "b", "path": "modules/b", "status": None, "time": None},
        {"kind": "plan", "id": "p", "path": "plans/p/plan.md", "status": None, "time": None},
    ]
    assert [list(n.keys()) for n in data["nodes"]] == [["kind", "id", "path", "status", "time"]] * 6
    assert [(e["kind"], e["src"], e["dst"], e["via"]) for e in data["edges"]] == [
        ("covers", "doc:docs/дока.md", "module:a", "table"),
        ("refs", "commit:ccc1", "plan:p", "trailer:Refs"),
        ("touches", "commit:ccc1", "module:a", "path"),
        ("touches", "commit:ccc1", "module:a", "table"),
        ("touches", "commit:ccc1", "module:b", "path"),
        ("touches", "commit:ccc2", "module:a", "path"),
    ]
    assert [(f["code"], f["node"], f["detail"]) for f in data["findings"]] == [
        ("BROKEN_LINK", "commit:ccc1", "z.md"),
        ("BROKEN_LINK", "doc:docs/дока.md", "x.md"),
        ("BROKEN_LINK", "doc:docs/дока.md", "y.md"),
        ("REF_MOVED", "commit:ccc1", ""),
    ]


def test_cache_key_includes_main_ref_and_adapter_fingerprint(repo, atlas, set_adapters):
    from scripts.atlas.tests.conftest import MarkerAdapter

    repo.write("m.md", "# m\n@@finding blocking BROKEN_LINK doc:{path} x.md\n")
    fork = repo.commit("M: finding already here")
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("other.txt", "branch work\n")
    repo.commit("F: branch commit after M")

    # сборка на M без адаптеров кладёт в кэш пустой реестр с отпечатком "без адаптеров"
    set_adapters()
    cold = atlas(repo, "build", "--ref", fork)
    assert cold.code == 0, cold.err

    # с адаптером отпечаток другой: ref-сборка пересчитана, находка есть на обеих сторонах
    set_adapters(MarkerAdapter())
    checked = atlas(repo, "check")
    assert checked.code == 0, checked.out + checked.err
    assert checked.out.strip().splitlines()[-1] == "atlas check: 0 new blocking, 0 new warning, 0 new info"

    # main_ref входит в ключ: сборка с main не отвечает на запрос с веткой X
    repo.git("branch", "X", fork)
    set_adapters()
    built = atlas(repo, "build")
    assert built.code == 0, built.err
    default = json.loads(atlas(repo, "--json").out)
    custom = atlas(repo, "--json", "--main-ref", "X")
    assert custom.code == 0, custom.err
    assert default["main_ref"] == "main"
    assert json.loads(custom.out)["main_ref"] == "X"
