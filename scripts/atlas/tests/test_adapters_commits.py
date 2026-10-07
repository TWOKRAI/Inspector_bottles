"""Приёмочные тесты адаптера `commits` (Task 1.3b, RED до кода).

Purpose: узлы commit, рёбра refs/implements/touches/done_by, находки DONE_* и COMMIT_WITHOUT_DONE на
    временных репозиториях и на реальном checkout (пины 4aee917c6); запрос ядра про модули без узла.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы; оракулы — независимые вызовы git (rev-parse, log, rev-list). Вывод подпроцессов
сравнивается значениями (json.loads); весь stderr — строкой с `\n` в конце. Каталог `data/` временных
репозиториев исключён через .git/info/exclude, чтобы `git add .` не забрал базу реестра.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "4aee917c6"
_OLD_PIN = "06a70f7e6"
_CO = "Co-Authored-By: Test <test@example.invalid>"
_PLAN_ALPHA = "plans/2026-10-01_alpha/plan.md"
_MODULES = """version: 1
modules:
  - id: a
    paths: ["a/"]
    layer: scripts
    tier: null
    docs: []
    parent: null
  - id: a/sub
    paths: ["a/sub/"]
    layer: scripts
    tier: null
    docs: []
    parent: a
"""


def _new_repo(factory: RepoFactory, name: str) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    return repo


def _doc(repo: GitRepo, atlas: Any, ref: str, main_ref: str = "main") -> dict[str, Any]:
    res = atlas(repo, "--json", "--ref", ref, "--main-ref", main_ref)
    assert res.code == 0, res.err
    return json.loads(res.out)


def _ids(doc: dict[str, Any], kind: str) -> list[str]:
    return sorted(n["id"] for n in doc["nodes"] if n["kind"] == kind)


def _edges(doc: dict[str, Any], kind: str, src: str | None = None) -> list[tuple[str, str, str]]:
    return sorted((e["src"], e["dst"], e["via"]) for e in doc["edges"] if e["kind"] == kind and src in (None, e["src"]))


def _findings(doc: dict[str, Any], code: str | None = None) -> list[tuple[str, str, str, str, str]]:
    return sorted(
        (f["code"], f["severity"], f["node"], f["detail"], f["source"])
        for f in doc["findings"]
        if code in (None, f["code"])
    )


def _plan(*rows: str) -> str:
    return "# Alpha\n\n## Порядок выполнения\n\n" + "".join(f"- Task {row}\n" for row in rows)


def _pr_repo(factory: RepoFactory) -> tuple[GitRepo, dict[str, str]]:
    """A на main; feat (F1, F2) влита --no-ff -> M; pr = M + P1; q = M + Q1 влита --no-ff в pr -> X."""
    repo = _new_repo(factory, "pr_repo")
    shas: dict[str, str] = {}
    repo.write("f.txt", "A\n")
    shas["A"] = repo.commit("A")
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("f.txt", "F1\n")
    shas["F1"] = repo.commit("F1")
    repo.write("f.txt", "F2\n")
    shas["F2"] = repo.commit("F2")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "M", "feat")
    shas["M"] = repo.head
    repo.git("checkout", "-q", "-b", "pr")
    repo.write("p.txt", "P1\n")
    shas["P1"] = repo.commit("P1")
    repo.git("checkout", "-q", "-b", "q", shas["M"])
    repo.write("q.txt", "Q1\n")
    shas["Q1"] = repo.commit("Q1")
    repo.git("checkout", "-q", "pr")
    repo.git("merge", "-q", "--no-ff", "-m", "X", "q")
    shas["X"] = repo.head
    repo.git("checkout", "-q", "main")
    return repo, shas


def test_commit_nodes_first_parent_and_pr_set(repo_factory: RepoFactory, atlas: Any) -> None:
    repo, shas = _pr_repo(repo_factory)  # SHA — вывод `git rev-parse HEAD` сразу после коммита
    assert repo.git("rev-parse", "main") == shas["M"]

    doc = _doc(repo, atlas, "main")
    nodes = [n for n in doc["nodes"] if n["kind"] == "commit"]
    assert sorted(n["id"] for n in nodes) == sorted([shas["M"], shas["A"]])
    assert shas["F1"] not in {n["id"] for n in nodes}
    assert shas["F2"] not in {n["id"] for n in nodes}
    for node in nodes:
        assert node["path"] is None
        assert node["status"] is None
        assert node["time"] == int(repo.git("log", "-1", "--format=%ct", node["id"]))

    doc = _doc(repo, atlas, "pr")
    assert _ids(doc, "commit") == sorted([shas["X"], shas["P1"], shas["Q1"], shas["M"], shas["A"]])


def test_nodes_follow_the_build_sha_not_the_main_tip(repo_factory: RepoFactory, atlas: Any) -> None:
    repo, shas = _pr_repo(repo_factory)
    doc = _doc(repo, atlas, shas["A"])
    assert _ids(doc, "commit") == [shas["A"]]
    assert shas["M"] not in _ids(doc, "commit")


def test_trailer_edges_refs_and_implements(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "trailers")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [DONE 2026-10-01]", "1.2: second [PENDING]"))
    repo.write("plans/beta.md", _plan("1.1: only [PENDING]"))
    repo.commit("plans")
    old_form = (
        "chore: old form\n\n"
        "Refs: plans/2026-10-01_alpha/plan.md\n"
        "Refs: plans/beta.md\n"
        "Refs: plans/_archive/2026-05-01_old/plan.md\n"
        "Refs: plans/2026-10-01_alpha/tasks/1.2.md\n"
        "Refs: docs/notes.md\n"
        "Task: alpha#1.2\n"
        "Task: alpha#1.2\n"
        "Task: ghost#9.9\n"
        "Task: nohash\n"
        "see Refs: plans/gamma.md\n"
        f"\n{_CO}"
    )
    repo.write("README.md", "c\n")
    c = repo.commit(old_form)
    repo.write("README.md", "d\n")
    d = repo.commit(f"fix: one block\n\nRefs: plans/beta.md\nTask: alpha#1.2\n{_CO}")

    doc = _doc(repo, atlas, "main")
    src = f"commit:{c}"
    assert _edges(doc, "refs", src) == [
        (src, "plan:alpha", "trailer:Refs"),
        (src, "plan:beta", "trailer:Refs"),
        (src, "plan:old", "trailer:Refs"),
    ]
    assert _edges(doc, "implements", src) == [
        (src, "task:alpha#1.2", "trailer:Task"),
        (src, "task:ghost#9.9", "trailer:Task"),
    ]

    # оракул: у коммита D (один блок) git сам видит те же трейлеры
    assert repo.git("log", "-1", "--format=%(trailers:key=Refs,valueonly)", d) == "plans/beta.md"
    assert repo.git("log", "-1", "--format=%(trailers:key=Task,valueonly)", d) == "alpha#1.2"
    src_d = f"commit:{d}"
    assert _edges(doc, "refs", src_d) == [(src_d, "plan:beta", "trailer:Refs")]
    assert _edges(doc, "implements", src_d) == [(src_d, "task:alpha#1.2", "trailer:Task")]


def test_touches_edges(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "touches")
    repo.write("modules.yaml", _MODULES)
    repo.commit("modules")
    repo.write("a/x.py", "x\n")
    repo.write("a/sub/y.py", "y\n")
    repo.write("README.md", "r\n")
    k1 = repo.commit("K1")
    repo.git("mv", "a/x.py", "a/sub/x.py")
    k2 = repo.commit("K2 rename")
    repo.git("checkout", "-q", "-b", "side")
    repo.write("a/z.py", "z\n")
    repo.commit("side change")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "M", "side")
    m = repo.head

    doc = _doc(repo, atlas, m)
    assert _ids(doc, "module") == ["a", "a/sub"]  # узла module:other нет
    assert _edges(doc, "touches", f"commit:{k1}") == [
        (f"commit:{k1}", "module:a", "path"),
        (f"commit:{k1}", "module:a/sub", "path"),
        (f"commit:{k1}", "module:other", "path"),
    ]
    assert _edges(doc, "touches", f"commit:{k2}") == [
        (f"commit:{k2}", "module:a", "path"),
        (f"commit:{k2}", "module:a/sub", "path"),
    ]
    assert _edges(doc, "touches", f"commit:{m}") == [(f"commit:{m}", "module:a", "path")]

    bare = _new_repo(repo_factory, "touches_root")
    bare.write("b.txt", "b\n")
    root_commit = bare.commit("root")
    doc = _doc(bare, atlas, root_commit)
    assert _ids(doc, "module") == []
    assert _edges(doc, "touches", f"commit:{root_commit}") == [(f"commit:{root_commit}", "module:other", "path")]


def test_done_by_resolves_short_hashes_and_adds_side_branch_commits(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "done_by")
    repo.write("f.txt", "A\n")
    a = repo.commit("A")
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("s.txt", "S\n")
    s = repo.commit("S")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "M", "feat")
    repo.git("tag", "-a", "t1", "-m", "x", s)
    tag_object = repo.git("rev-parse", "t1")
    assert tag_object != s
    repo.write(
        _PLAN_ALPHA,
        _plan(
            f"1.1: eight [DONE 2026-10-01] `{s[:8]}`",
            f"1.2: nine [DONE 2026-10-01] `{s[:9]}`",
            f"1.3: full [DONE 2026-10-01] `{a}`",
            f"1.4: not done [PENDING] `{s[:8]}`",
            f"1.5: tag [DONE 2026-10-01] `{tag_object[:8]}`",
        ),
    )
    repo.commit("plan")

    doc = _doc(repo, atlas, "main")
    assert s in _ids(doc, "commit")  # не first-parent: коммит влитой ветки
    assert _edges(doc, "done_by") == [
        ("task:alpha#1.1", f"commit:{s}", "plan-line"),
        ("task:alpha#1.2", f"commit:{s}", "plan-line"),
        ("task:alpha#1.3", f"commit:{a}", "plan-line"),
        ("task:alpha#1.5", f"commit:{s}", "plan-line"),
    ]
    assert _findings(doc, "DONE_HASH_NOT_IN_MAIN") == []


def test_done_hash_unresolved_or_not_in_main(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "not_in_main")
    repo.write("f.txt", "A\n")
    repo.commit("A")
    repo.git("checkout", "-q", "-b", "side")
    repo.write("u.txt", "U\n")
    u = repo.commit("U")
    repo.git("checkout", "-q", "main")
    repo.write(
        _PLAN_ALPHA,
        _plan(
            f"1.1: unmerged [DONE 2026-10-01] `{u[:8]}`",
            "1.2: nowhere [DONE 2026-10-01] `deadbeef`",
        ),
    )
    repo.commit("plan")

    doc = _doc(repo, atlas, "main")
    assert _findings(doc) == [
        ("DONE_HASH_NOT_IN_MAIN", "blocking", "task:alpha#1.1", u[:8], _PLAN_ALPHA),
        ("DONE_HASH_NOT_IN_MAIN", "blocking", "task:alpha#1.2", "deadbeef", _PLAN_ALPHA),
    ]
    assert _edges(doc, "done_by") == [("task:alpha#1.1", f"commit:{u}", "plan-line")]
    assert u in _ids(doc, "commit")
    assert all(not cid.startswith("deadbeef") for cid in _ids(doc, "commit"))


def test_done_without_commit_and_commit_without_done(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "dwc")
    repo.write("f.txt", "H\n")
    h = repo.commit("H")
    repo.write(
        _PLAN_ALPHA,
        _plan(
            "1.1: no commit [DONE 2026-10-01]",
            "1.2: named by a commit [DONE 2026-10-01]",
            "1.3: pending but named [PENDING]",
            f"1.4: hashed [DONE 2026-10-01] `{h}`",
            "1.5: pending alone [PENDING]",
        ),
    )
    repo.commit("plan")
    repo.write("f.txt", "2\n")
    repo.commit(f"feat: two\n\nTask: alpha#1.2\n{_CO}")
    repo.write("f.txt", "3\n")
    x3 = repo.commit(f"feat: three\n\nTask: alpha#1.3\n{_CO}")
    repo.write("f.txt", "g\n")
    repo.commit(f"feat: ghost\n\nTask: ghost#9.9\n{_CO}")

    doc = _doc(repo, atlas, "main")
    assert _findings(doc) == [
        ("COMMIT_WITHOUT_DONE", "info", "task:alpha#1.3", "", x3),
        ("DONE_WITHOUT_COMMIT", "info", "task:alpha#1.1", "", _PLAN_ALPHA),
    ]


def test_main_ref_missing_and_shallow_exit_2(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "full")
    for n in range(3):
        repo.write("f.txt", f"{n}\n")
        repo.commit(f"c{n}")
    res = atlas(repo, "build", "--ref", repo.head, "--main-ref", "nope")
    assert res.code == 2
    assert res.err == "atlas: main ref not found\n"

    shallow = repo_factory.clone_shallow(repo, "shallow")
    res = atlas(shallow, "--json", "--ref", "HEAD", "--main-ref", "HEAD")
    assert res.code == 2
    assert res.err == "atlas: shallow clone — commits need full history; run: git fetch --unshallow\n"


def _real_doc(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Сборка на реальном checkout со СВЕЖЕЙ базой (data/atlas.sqlite кэширует сборки по sha и отпечатку)."""
    from scripts.atlas import store

    real_connect = store.connect
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real_connect(tmp_path / "fresh" / "atlas.sqlite"))
    checkout = GitRepo(_ROOT)
    shallow = checkout.git("rev-parse", "--is-shallow-repository")
    assert shallow == "false", "checkout неглубокий: выполнить `git fetch --unshallow`"
    assert checkout.git("rev-parse", "--verify", f"{_PIN}^{{commit}}"), f"в клоне нет коммита {_PIN}"
    return _doc(checkout, atlas, _PIN, _PIN)


def test_pinned_counts_on_this_checkout(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _real_doc(atlas, monkeypatch, tmp_path)
    counts = {kind: len(_ids(doc, kind)) for kind in ("commit", "module", "plan", "task")}
    assert counts == {"commit": 2229, "module": 87, "plan": 148, "task": 1240}
    edge_counts = {kind: len(_edges(doc, kind)) for kind in ("refs", "implements", "touches", "done_by")}
    assert edge_counts == {"refs": 1622, "implements": 33, "touches": 5152, "done_by": 312}
    assert sum(1 for _, dst, _ in _edges(doc, "touches") if dst == "module:other") == 2002
    codes = [f["code"] for f in doc["findings"]]
    assert codes.count("DONE_WITHOUT_COMMIT") == 310
    assert codes.count("COMMIT_WITHOUT_DONE") == 3
    assert codes.count("DONE_HASH_NOT_IN_MAIN") == 0
    assert codes.count("PLAN_SLUG_COLLISION") == 0
    assert sorted(f["node"] for f in doc["findings"] if f["code"] == "COMMIT_WITHOUT_DONE") == [
        "task:atlas#1.3a",
        "task:atlas#2.4",
        "task:commit-mechanism#3.1",
    ]


def _slug(value: str) -> str | None:
    """Правило DESIGN п. 2: `plans/[_archive/]<сегмент>[/…].md` -> сегмент без `.md` и без даты."""
    if not (value.startswith("plans/") and value.endswith(".md")):
        return None
    rest = value[len("plans/") :]
    rest = rest.removeprefix("_archive/")
    segment = rest.split("/", 1)[0].removesuffix(".md")
    return re.sub(r"^\d{4}-\d{2}-\d{2}_", "", segment)


def test_thirty_day_touches_and_trailer_oracle(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _real_doc(atlas, monkeypatch, tmp_path)
    checkout = GitRepo(_ROOT)
    pin_time = int(checkout.git("log", "-1", "--format=%ct", _PIN))
    rows = [line.split(" ") for line in checkout.git("log", "--first-parent", "--format=%H %ct", _PIN).splitlines()]
    recent = [sha for sha, ts in rows if int(ts) >= pin_time - 30 * 86400]
    assert len(recent) == 370
    touched: dict[str, set[str]] = {}
    for src, dst, _ in _edges(doc, "touches"):
        touched.setdefault(src.removeprefix("commit:"), set()).add(dst)
    assert all(touched.get(sha) for sha in recent)
    only_other = [sha for sha in recent if touched[sha] == {"module:other"}]
    assert len(recent) - len(only_other) == 181
    assert len(only_other) == 189

    sep = "\x01"
    raw = checkout.git(
        "log",
        "--first-parent",
        f"--format={sep}%H\x02%(trailers:key=Task,valueonly)\x02%(trailers:key=Refs,valueonly)",
        f"{_OLD_PIN}..{_PIN}",
    )
    implements: dict[str, set[str]] = {}
    for src, dst, _ in _edges(doc, "implements"):
        implements.setdefault(src.removeprefix("commit:"), set()).add(dst)
    refs: dict[str, set[str]] = {}
    for src, dst, _ in _edges(doc, "refs"):
        refs.setdefault(src.removeprefix("commit:"), set()).add(dst)
    entries = [entry for entry in raw.split(sep) if entry.strip()]
    assert len(entries) == 39
    with_task = with_refs = 0
    for entry in entries:
        sha, task_text, refs_text = entry.split("\x02")
        sha = sha.strip()
        tasks = {f"task:{line.strip()}" for line in task_text.splitlines() if line.strip()}
        slugs = {f"plan:{_slug(line.strip())}" for line in refs_text.splitlines() if _slug(line.strip())}
        with_task += bool(tasks)
        with_refs += bool(slugs)
        assert implements.get(sha, set()) == tasks, sha
        assert refs.get(sha, set()) == slugs, sha
    assert (with_task, with_refs) == (21, 39)


def test_modules_without_contract_test_skips_module_without_node(tmp_path: Path) -> None:
    from scripts.atlas.schema import AdapterOutput, Edge, Node
    from scripts.atlas.store import connect, modules_without_contract_test, write_build

    nodes = [
        Node(kind="commit", id="c1", path=None, status=None, time=100),
        Node(kind="module", id="a", path="modules.yaml", status=None, time=None),
    ]
    edges = [
        Edge(kind="touches", src="commit:c1", dst="module:a", via="path"),
        Edge(kind="touches", src="commit:c1", dst="module:other", via="path"),
    ]
    con = connect(tmp_path / "atlas.sqlite")
    try:
        first = write_build(con, "a" * 40, "main", "fp", AdapterOutput(nodes=nodes, edges=edges, findings=[]))
        assert modules_without_contract_test(con, first, 0) == ["a"]
        with_other = [*nodes, Node(kind="module", id="other", path="modules.yaml", status=None, time=None)]
        second = write_build(con, "b" * 40, "main", "fp", AdapterOutput(nodes=with_other, edges=edges, findings=[]))
        assert modules_without_contract_test(con, second, 0) == ["a", "other"]
    finally:
        con.close()
