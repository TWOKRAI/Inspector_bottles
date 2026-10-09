"""Приёмочные тесты адаптера `commits` (Task 1.3b, 1.3c и правки 1.3c после слияния PR #16; RED до кода).

Purpose: узлы commit, рёбра refs/implements/touches/done_by, находки DONE_*, COMMIT_WITHOUT_DONE и REF_* на
    временных репозиториях и на реальном checkout (пины 4aee917c6, 712ce64a1, a5ae9657a); запрос ядра про
    модули без узла. Правки 1.3c: левая граница токена Refs (О10), служебные имена не планы (О11),
    трейлеры ВСЕХ коммитов-предков без слияний (трейлеры слияний игнорируются). Правки 1.3c раунд 2: узел commit
    у каждого коммита без слияний с трейлером Refs:/Task: (у каждого ребра и находки есть узел-источник);
    константа служебных имён `_SERVICE_NAMES` и `_is_service_name` в адаптере (без импорта plans_progress;
    литеральные пины SERVICE_NAMES/RESULT_FILE_RE источника); версия адаптера 4; проверка узла-источника
    у рёбер и находок — внутри пин-тестов на реальном checkout.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы; оракулы — независимые вызовы git (rev-parse, log, rev-list). Вывод подпроцессов
сравнивается значениями (json.loads); весь stderr — строкой с `\n` в конце. Каталог `data/` временных
репозиториев исключён через .git/info/exclude, чтобы `git add .` не забрал базу реестра.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "4aee917c6"
_PIN_FULL = "712ce64a1a39723ddadf9a6acd3e7d40ff326d11"
_PIN_A5 = "a5ae9657a5bc3aacea61deaa01c1ac212e310ae5"
_OLD_PIN = "06a70f7e6"
# (SHA, значение Task) — находки REF_TO_MISSING «в плане нет задачи»: одни и те же на пинах 712ce64a1 и a5ae9657a
_TASK_MISSING = [
    ("184c6cc55bb9a0fe487c38b60ec086f98f5832e3", "atlas#2.4e"),
    ("1b99f74bab33a27728598d9e02801983012f46eb", "atlas#2.4g"),
    ("1cdd69294cd6a247f9aff4e402baae5bdfb54a97", "atlas#2.4g"),
    ("25883b241e9207428b8e6a24626c56b1a2772dba", "atlas#2.4g"),
    ("26daa292ee70a7b6a1173c94d3375d27578a336a", "atlas#2.4e"),
    ("3187699f903f875af7e0ed71f6043ba517f9fea3", "atlas#2.4g"),
    ("327c210571bd82cbbfe0e39ff8b7dfde0aa38e9c", "atlas#2.4g"),
    ("39780cb43811a969597e14b6c0cc57dc7abb86fc", "atlas#2.4b"),
    ("39df3e8dd666aea90d127303a1efc7a6896d0669", "atlas#2.4g"),
    ("3eae81af5d54601cd80d17e8b72c1357fccb5356", "atlas#2.4e"),
    ("51d6f1c269cf784926b5d23eb864ba0c5752bb94", "atlas#2.4g"),
    ("6fbf8a102c400e08998ae6e480ee550d5be03f17", "atlas#2.4c"),
    ("878d485c7f95f8f5c508551c5b141c9029f0fa51", "atlas#2.4g"),
    ("971719f99afaa8f106cb60a27750f7bfdc7c9d42", "atlas#2.4g"),
    ("9e6ae3c29e378ce123fdcdb377682cf877a171fe", "atlas#2.4g"),
    ("9f7bb8b83cdb78267d14797a7171d8e5eafb1e5a", "atlas#2.4g"),
    ("a52c4241d749efbb6b713fc22bd019d491842487", "atlas#2.4g"),
    ("aeeb471f3192f10c9b755ca4b5accbc5538837e8", "atlas#2.4g"),
    ("dd9835f071556b07c3026aa081bcf1f963323702", "atlas#2.4g"),
]
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
    ghost = repo.commit(f"feat: ghost\n\nTask: ghost#9.9\n{_CO}")

    doc = _doc(repo, atlas, "main")
    assert _findings(doc) == [
        ("COMMIT_WITHOUT_DONE", "info", "task:alpha#1.3", "", x3),
        ("DONE_WITHOUT_COMMIT", "info", "task:alpha#1.1", "", _PLAN_ALPHA),
        ("REF_TO_MISSING", "blocking", f"commit:{ghost}", "ghost#9.9", ghost),
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


def _real_doc(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pin: str = _PIN) -> dict[str, Any]:
    """Сборка на реальном checkout со СВЕЖЕЙ базой (data/atlas.sqlite кэширует сборки по sha и отпечатку)."""
    from scripts.atlas import store

    real_connect = store.connect
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real_connect(tmp_path / "fresh" / "atlas.sqlite"))
    checkout = GitRepo(_ROOT)
    shallow = checkout.git("rev-parse", "--is-shallow-repository")
    assert shallow == "false", "checkout неглубокий: выполнить `git fetch --unshallow`"
    probe = run_with_deadline(
        lambda: subprocess.run(
            ["git", "cat-file", "-t", pin], cwd=_ROOT, capture_output=True, text=True, encoding="utf-8", check=False
        )
    )
    assert probe.stdout.strip() == "commit", f"в клоне нет коммита {pin} (нужен полный клон: git fetch --unshallow)"
    return _doc(checkout, atlas, pin, pin)


def _sha_set(args: list[str]) -> set[str]:
    return set(GitRepo(_ROOT).git(*args).split())


def _no_bad_chars_in_refs(doc: dict[str, Any]) -> list[str]:
    return [dst for _, dst, _ in _edges(doc, "refs") if any(ch in dst for ch in ", ;()")]


def _dangling_refs(doc: dict[str, Any]) -> int:
    plan_nodes = {f"plan:{pid}" for pid in _ids(doc, "plan")}
    return sum(1 for _, dst, _ in _edges(doc, "refs") if dst not in plan_nodes)


def _assert_task_findings_missing(doc: dict[str, Any]) -> None:
    found = sorted(
        (f["code"], f["severity"], f["node"], f["detail"], f["source"], f["message"])
        for f in doc["findings"]
        if f["code"] == "REF_TO_MISSING" and "#" in f["detail"]
    )
    expected = sorted(
        (
            "REF_TO_MISSING",
            "blocking",
            f"commit:{sha}",
            value,
            sha,
            f"Task: в плане atlas нет задачи {value.split('#', 1)[1]}",
        )
        for sha, value in _TASK_MISSING
    )
    assert len(expected) == 19
    assert found == expected


def _assert_no_orphan_refs(doc: dict[str, Any]) -> None:
    """0 рёбер refs/implements без узла-источника и 0 находок REF_* без узла commit."""
    node_ids = set(_ids(doc, "commit"))
    ref_edges = _edges(doc, "refs") + _edges(doc, "implements")
    assert len(ref_edges) > 100  # предусловие осмысленности: рёбра-источники вообще есть
    assert [src for src, _, _ in ref_edges if src.removeprefix("commit:") not in node_ids] == []
    ref_findings = [f for f in doc["findings"] if f["code"] in _REF_CODES]
    assert len(ref_findings) > 100
    assert [f["node"] for f in ref_findings if f["node"].removeprefix("commit:") not in node_ids] == []


def test_pinned_counts_on_this_checkout(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _real_doc(atlas, monkeypatch, tmp_path)
    counts = {kind: len(_ids(doc, kind)) for kind in ("commit", "module", "plan", "task")}
    assert counts == {"commit": 4580, "module": 87, "plan": 148, "task": 1240}
    edge_counts = {kind: len(_edges(doc, kind)) for kind in ("refs", "implements", "touches", "done_by")}
    assert edge_counts == {"refs": 4053, "implements": 145, "touches": 5152, "done_by": 312}
    assert sum(1 for _, dst, _ in _edges(doc, "touches") if dst == "module:other") == 2002
    assert _no_bad_chars_in_refs(doc) == []
    assert _dangling_refs(doc) == 140
    codes = [f["code"] for f in doc["findings"]]
    assert codes.count("DONE_WITHOUT_COMMIT") == 310
    assert codes.count("COMMIT_WITHOUT_DONE") == 3
    assert codes.count("DONE_HASH_NOT_IN_MAIN") == 0
    assert codes.count("PLAN_SLUG_COLLISION") == 0
    assert codes.count("REF_TO_MISSING") == 58
    assert codes.count("REF_MOVED") == 1076
    assert sorted(f["node"] for f in doc["findings"] if f["code"] == "COMMIT_WITHOUT_DONE") == [
        "task:atlas#1.3a",
        "task:atlas#2.4",
        "task:commit-mechanism#3.1",
    ]
    _assert_no_orphan_refs(doc)


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
    merges = _sha_set(["log", "--first-parent", "--merges", "--format=%H", f"{_OLD_PIN}..{_PIN}"])
    assert len(merges) == 23  # все 23 слияния диапазона несут трейлеры Refs/Task — и обязаны их потерять
    for sha in merges:
        assert implements.get(sha, set()) == set(), sha
        assert refs.get(sha, set()) == set(), sha
    with_task = with_refs = 0
    checked = 0
    for entry in entries:
        sha, task_text, refs_text = entry.split("\x02")
        sha = sha.strip()
        if sha in merges:
            continue
        checked += 1
        tasks = {f"task:{line.strip()}" for line in task_text.splitlines() if line.strip()}
        slugs = {f"plan:{_slug(line.strip())}" for line in refs_text.splitlines() if _slug(line.strip())}
        with_task += bool(tasks)
        with_refs += bool(slugs)
        assert implements.get(sha, set()) == tasks, sha
        assert refs.get(sha, set()) == slugs, sha
    assert (checked, with_task, with_refs) == (16, 9, 16)


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


_REF_CODES = ("REF_TO_MISSING", "REF_MOVED")
_PATH_GONE = "Refs: путь {} не найден ни в дереве сборки, ни в дереве коммита"
_PATH_MOVED = "Refs: путь {} есть в дереве коммита, но не в дереве сборки (перенос или архив)"
_PLAN_GONE = "Task: план {} не найден ни в дереве сборки, ни в дереве коммита"
_PLAN_MOVED = "Task: план {} есть в дереве коммита, но не в дереве сборки (перенос или архив)"


def _ref_findings(doc: dict[str, Any]) -> list[tuple[str, str, str, str, str, str]]:
    """REF_*-находки как (code, severity, node, detail, source, message), по порядку."""
    return sorted(
        (f["code"], f["severity"], f["node"], f["detail"], f["source"], f["message"])
        for f in doc["findings"]
        if f["code"] in _REF_CODES
    )


def _msg(*parts: str) -> str:
    return f"{parts[0]}\n\n" + "\n".join(parts[1:]) + f"\n\n{_CO}"


def test_refs_value_splits_into_plan_tokens(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "tokens")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]"))
    repo.write("plans/beta.md", _plan("1.1: only [PENDING]"))
    repo.commit("plans")
    repo.write("README.md", "c\n")
    c = repo.commit(
        _msg(
            "chore: tokens",
            "Refs: plans/2026-10-01_alpha/plan.md, plans/beta.md",
            "Refs: docs/x.md, plans/gamma.md (see plans/delta.md); plans/eps.md",
            "Refs: plans/zeta.md.",
            "Refs: plans/beta.md, plans/gamma.md",
        )
    )

    doc = _doc(repo, atlas, "main")
    src = f"commit:{c}"
    assert _edges(doc, "refs", src) == [
        (src, f"plan:{slug}", "trailer:Refs") for slug in ("alpha", "beta", "delta", "eps", "gamma", "zeta")
    ]
    for _, dst, _ in _edges(doc, "refs"):
        assert not any(ch in dst for ch in ", ;()") and not dst.endswith(".")
    assert _ref_findings(doc) == [
        ("REF_TO_MISSING", "blocking", src, path, c, _PATH_GONE.format(path))
        for path in ("plans/delta.md", "plans/eps.md", "plans/gamma.md", "plans/zeta.md")
    ]


def test_ref_findings_by_path(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "by_path")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]"))
    repo.write("plans/beta.md", _plan("1.1: only [PENDING]"))
    repo.write("plans/dirx/readme.md", "dir\n")
    repo.commit("c1 plans")
    repo.write("README.md", "x\n")
    x = repo.commit(
        _msg(
            "chore: refs by path",
            "Refs: plans/beta.md",
            "Refs: plans/typo.md",
            "Refs: plans/2026-10-01_alpha/tasks/9.md",
            "Refs: plans/dirx/",
            "Refs: plans/late.md",
            "Refs: plans/2026-10-01_alpha/plan.md",
            "Refs: docs/missing.md",
        )
    )
    repo.write("plans/late.md", _plan("1.1: late [PENDING]"))
    repo.commit("c3 late")
    repo.git("rm", "-q", "plans/beta.md")
    repo.commit("c4 rm beta")

    doc = _doc(repo, atlas, "main")
    node = f"commit:{x}"
    deep = "plans/2026-10-01_alpha/tasks/9.md"
    assert _ref_findings(doc) == [
        ("REF_MOVED", "info", node, "plans/beta.md", x, _PATH_MOVED.format("plans/beta.md")),
        ("REF_TO_MISSING", "blocking", node, deep, x, _PATH_GONE.format(deep)),
        ("REF_TO_MISSING", "blocking", node, "plans/typo.md", x, _PATH_GONE.format("plans/typo.md")),
    ]


def test_task_ref_findings_missing_plan_and_missing_id(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "task_refs")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]"))
    repo.commit("plan")
    repo.write("f.txt", "1\n")
    t1 = repo.commit(_msg("feat: t1", "Task: alpha#1.1"))
    repo.write("f.txt", "2\n")
    t2 = repo.commit(_msg("feat: t2", "Task: alpha#9.9", "Task: alpha#9.9"))
    repo.write("f.txt", "3\n")
    t3 = repo.commit(_msg("feat: t3", "Task: ghost#1.1"))
    repo.write("f.txt", "4\n")
    repo.commit(_msg("feat: t4", "Task: nohash", "Task: #5", "Task: x#"))

    doc = _doc(repo, atlas, "main")
    assert _findings(doc) == sorted(
        [
            ("COMMIT_WITHOUT_DONE", "info", "task:alpha#1.1", "", t1),
            ("REF_TO_MISSING", "blocking", f"commit:{t2}", "alpha#9.9", t2),
            ("REF_TO_MISSING", "blocking", f"commit:{t3}", "ghost#1.1", t3),
        ]
    )
    assert _ref_findings(doc) == sorted(
        [
            ("REF_TO_MISSING", "blocking", f"commit:{t2}", "alpha#9.9", t2, "Task: в плане alpha нет задачи 9.9"),
            ("REF_TO_MISSING", "blocking", f"commit:{t3}", "ghost#1.1", t3, _PLAN_GONE.format("ghost")),
        ]
    )
    assert _edges(doc, "implements") == sorted(
        [
            (f"commit:{t1}", "task:alpha#1.1", "trailer:Task"),
            (f"commit:{t2}", "task:alpha#9.9", "trailer:Task"),
            (f"commit:{t3}", "task:ghost#1.1", "trailer:Task"),
        ]
    )


def test_task_ref_moved_when_plan_was_in_commit_tree(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "task_moved")
    one = _plan("1.1: x [PENDING]")
    for rel in (
        "plans/2026-09-01_old/plan.md",
        "plans/2026-09-02_ren/plan.md",
        "plans/2026-09-03_arch/plan.md",
        "plans/2026-09-04_keep/plan.md",
        "plans/2026-09-05_gone/plan.md",
        "plans/_archive/2026-09-06_z/plan.md",
        "plans/flat.md",
    ):
        repo.write(rel, one)
    repo.commit("P plans")
    shas: dict[str, str] = {}
    for n, (key, slug) in enumerate(
        (("K1", "old"), ("K2", "ren"), ("K3", "arch"), ("K4", "keep"), ("K6", "z"), ("K7", "flat"))
    ):
        repo.write("f.txt", f"{n}\n")
        shas[key] = repo.commit(_msg(f"feat: {key}", f"Task: {slug}#1.1"))
    repo.git("rm", "-q", "-r", "plans/2026-09-01_old")
    repo.git("mv", "plans/2026-09-02_ren", "plans/2026-09-02_ren2")
    repo.git("mv", "plans/2026-09-03_arch", "plans/_archive/2026-09-03_arch")
    repo.git("rm", "-q", "-r", "plans/2026-09-05_gone")
    repo.git("rm", "-q", "-r", "plans/_archive/2026-09-06_z")
    repo.git("rm", "-q", "plans/flat.md")
    repo.commit("R move and remove plans")
    repo.write("f.txt", "k5\n")
    shas["K5"] = repo.commit(_msg("feat: K5", "Task: gone#1.1"))

    doc = _doc(repo, atlas, "main")
    expected = [
        ("REF_MOVED", "info", f"commit:{shas[key]}", f"{slug}#1.1", shas[key], _PLAN_MOVED.format(slug))
        for key, slug in (("K1", "old"), ("K2", "ren"), ("K6", "z"), ("K7", "flat"))
    ]
    expected.append(
        ("REF_TO_MISSING", "blocking", f"commit:{shas['K5']}", "gone#1.1", shas["K5"], _PLAN_GONE.format("gone"))
    )
    assert _ref_findings(doc) == sorted(expected)


def test_check_blocks_only_a_new_ref_to_missing(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "gate")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]"))
    repo.write("plans/beta.md", _plan("1.1: only [PENDING]"))
    repo.commit("plans")
    repo.write("f.txt", "L\n")
    repo.commit(_msg("chore: legacy", "Refs: plans/typo.md"))
    repo.write("f.txt", "O\n")
    o = repo.commit(_msg("chore: old ref", "Refs: plans/beta.md"))

    repo.git("checkout", "-q", "-b", "branch-a", "main")
    repo.write("f.txt", "a\n")
    repo.commit("a: no trailers")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 0, res.err
    assert res.out.splitlines() == ["atlas check: 0 new blocking, 0 new warning, 0 new info"]

    repo.git("checkout", "-q", "-b", "branch-b", "main")
    repo.write("f.txt", "b\n")
    n = repo.commit(_msg("b: typo", "Refs: plans/typo2.md"))
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 1, res.err
    assert res.out.splitlines() == [
        f"blocking REF_TO_MISSING commit:{n} plans/typo2.md",
        "atlas check: 1 new blocking, 0 new warning, 0 new info",
    ]

    repo.git("checkout", "-q", "-b", "branch-c", "main")
    repo.git("rm", "-q", "plans/beta.md")
    repo.commit("c: archive beta")
    res = atlas(repo, "check", "--main-ref", "main")
    assert res.code == 0, res.err
    assert res.out.splitlines() == [
        f"info REF_MOVED commit:{o} plans/beta.md",
        "atlas check: 0 new blocking, 0 new warning, 1 new info",
    ]


def _git_stdin(repo: GitRepo, data: bytes, *args: str) -> str:
    proc = run_with_deadline(
        lambda: subprocess.run(["git", *args], cwd=repo.path, input=data, capture_output=True, check=False)
    )
    assert proc.returncode == 0, f"git {' '.join(args)} -> {proc.returncode}: {proc.stderr!r}"
    return proc.stdout.decode("utf-8").strip()


def test_ambiguous_short_hash_is_not_missing(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "ambiguous")
    seen: dict[str, bytes] = {}
    i = 0
    while True:
        data = b"x%d\n" % i
        prefix = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:7]
        if prefix in seen:
            break
        seen[prefix] = data
        i += 1
    assert (i, prefix) == (22114, "71b710c")
    for blob in (seen[prefix], data):
        _git_stdin(repo, blob, "hash-object", "-w", "--stdin")
    repo.write(_PLAN_ALPHA, _plan(f"1.1: x [DONE 2026-10-01] `{prefix}`"))
    repo.commit("plan")

    doc = _doc(repo, atlas, "main")
    assert doc["findings"] == [
        {
            "code": "DONE_HASH_NOT_IN_MAIN",
            "severity": "blocking",
            "node": "task:alpha#1.1",
            "detail": "71b710c",
            "message": "Хеш в строке DONE задачи alpha#1.1: коммит неоднозначен",
            "source": _PLAN_ALPHA,
        }
    ]
    assert _edges(doc, "done_by") == []
    assert all(not cid.startswith("71b710c") for cid in _ids(doc, "commit"))


def test_short_hash_shared_with_a_blob_resolves_to_the_commit(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "T")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "t@example.invalid")
        monkeypatch.setenv(f"GIT_{key}_DATE", "1700000000 +0000")
    repo = _new_repo(repo_factory, "blob_commit")
    repo.write("f.txt", "A\n")
    a = repo.commit("A")
    tree = repo.git("rev-parse", "HEAD^{tree}")
    blobs: dict[str, bytes] = {}
    for n in range(200_000):
        data = b"x%d\n" % n
        blobs[hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:7]] = data
    found: tuple[str, bytes, bytes] | None = None
    for n in range(20_000):
        body = (
            f"tree {tree}\nparent {a}\nauthor T <t@example.invalid> 1700000000 +0000\n"
            f"committer T <t@example.invalid> 1700000000 +0000\n\nc{n}\n"
        ).encode()
        sha = hashlib.sha1(b"commit %d\0" % len(body) + body).hexdigest()
        if sha[:7] in blobs:
            found = (sha, body, blobs[sha[:7]])
            break
    assert found is not None, "за 20 000 вариантов коммита не нашлось общего 7-знакового префикса с блобом"
    c, body, blob = found
    _git_stdin(repo, blob, "hash-object", "-w", "--stdin")
    assert _git_stdin(repo, body, "hash-object", "-t", "commit", "-w", "--stdin") == c
    repo.git("update-ref", "refs/heads/main", c)
    verdict = _git_stdin(repo, f"{c[:7]}\n".encode(), "cat-file", "--batch-check")
    assert verdict == f"{c[:7]} ambiguous"
    repo.write(_PLAN_ALPHA, _plan(f"1.1: x [DONE 2026-10-01] `{c[:7]}`"))
    repo.commit("plan")

    doc = _doc(repo, atlas, "main")
    assert _edges(doc, "done_by") == [("task:alpha#1.1", f"commit:{c}", "plan-line")]
    assert c in _ids(doc, "commit")
    assert _findings(doc, "DONE_HASH_NOT_IN_MAIN") == []


def test_done_hash_messages_name_the_reason(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "reasons")
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
    assert sorted((f["node"], f["detail"], f["message"]) for f in doc["findings"]) == [
        ("task:alpha#1.1", u[:8], "Хеш в строке DONE задачи alpha#1.1: коммит не предок ревизии сборки"),
        ("task:alpha#1.2", "deadbeef", "Хеш в строке DONE задачи alpha#1.2: коммит не найден"),
    ]


def test_ref_findings_pinned_on_origin_main(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _real_doc(atlas, monkeypatch, tmp_path, _PIN_FULL)
    assert {kind: len(_ids(doc, kind)) for kind in ("commit", "module", "plan", "task")} == {
        "commit": 4603,
        "module": 87,
        "plan": 148,
        "task": 1242,
    }
    assert {kind: len(_edges(doc, kind)) for kind in ("refs", "implements", "touches", "done_by")} == {
        "refs": 4071,
        "implements": 163,
        "touches": 5160,
        "done_by": 313,
    }
    assert sum(1 for _, dst, _ in _edges(doc, "touches") if dst == "module:other") == 2008
    findings = doc["findings"]
    codes = [f["code"] for f in findings]
    assert {
        c: codes.count(c)
        for c in (
            "DONE_WITHOUT_COMMIT",
            "COMMIT_WITHOUT_DONE",
            "DONE_HASH_NOT_IN_MAIN",
            "PLAN_SLUG_COLLISION",
            "REF_TO_MISSING",
            "REF_MOVED",
        )
    } == {
        "DONE_WITHOUT_COMMIT": 310,
        "COMMIT_WITHOUT_DONE": 5,
        "DONE_HASH_NOT_IN_MAIN": 0,
        "PLAN_SLUG_COLLISION": 0,
        "REF_TO_MISSING": 59,
        "REF_MOVED": 1076,
    }
    missing = [f for f in findings if f["code"] == "REF_TO_MISSING"]
    moved = [f for f in findings if f["code"] == "REF_MOVED"]
    assert {f["severity"] for f in missing} == {"blocking"}
    assert {f["severity"] for f in moved} == {"info"}
    assert len({f["detail"] for f in moved}) == 101
    assert len({f["detail"] for f in missing}) == 20
    _assert_task_findings_missing(doc)
    pairs = {(f["code"], f["node"], f["detail"]) for f in findings}
    assert (
        "REF_TO_MISSING",
        "commit:06d8789cd9d12b1361b11c3c3f910181026fa19e",
        "plans/processes-workers-runtime.md",
    ) in pairs
    assert (
        "REF_MOVED",
        "commit:00781adb4157ac425ef2624bd57564905a201cf4",
        "plans/2026-06-06_command-result-bridge/plan.md",
    ) in pairs
    first_parent = _sha_set(["rev-list", "--first-parent", _PIN_FULL])
    assert sum(1 for f in moved if f["node"].removeprefix("commit:") not in first_parent) == 511
    _assert_no_orphan_refs(doc)


def test_refs_left_boundary(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "left_boundary")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]"))
    repo.write("plans/beta.md", _plan("1.1: only [PENDING]"))
    repo.commit("plans")
    repo.write("README.md", "c\n")
    c = repo.commit(
        _msg(
            "chore: left boundary",
            "Refs: docs/plans/x.md",
            "Refs: multiprocess_prototype/plans/y.md, ~/.claude/plans/z.md",
            "Refs: a plans/beta.md",
            "Refs: (plans/gamma.md)",
            "Refs: k,plans/delta.md",
            "Refs: k;plans/eps.md",
            "Refs: plans/beta.md,plans/zeta.md",
            "Refs: x/plans/w.md plans/v.md",
        )
    )

    doc = _doc(repo, atlas, "main")
    src = f"commit:{c}"
    assert _edges(doc, "refs", src) == [
        (src, f"plan:{slug}", "trailer:Refs") for slug in ("beta", "delta", "eps", "gamma", "v", "zeta")
    ]
    assert _ref_findings(doc) == [
        ("REF_TO_MISSING", "blocking", src, path, c, _PATH_GONE.format(path))
        for path in ("plans/delta.md", "plans/eps.md", "plans/gamma.md", "plans/v.md", "plans/zeta.md")
    ]


def test_task_service_names_are_not_plans(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "service_names")
    one = _plan("1.1: x [PENDING]")
    repo.write("plans/README.md", "# index\n")
    repo.write("plans/QUEUE.md", "# queue\n")
    repo.write("plans/queue/x.md", one)
    repo.write("plans/_archive/README.md", "# archive index\n")
    repo.write("plans/2026-09-01_old/plan.md", one)
    repo.write("plans/.hidden/plan.md", one)  # точечное имя записи — служебное
    repo.write("plans/old.result-1.1.md", "# result\n")  # итог задачи — не план
    repo.commit("plans")
    assert repo.git("ls-tree", "--name-only", "HEAD", "plans/").splitlines().count("plans/.hidden") == 1
    assert repo.git("ls-tree", "--name-only", "HEAD", "plans/").splitlines().count("plans/old.result-1.1.md") == 1
    shas: dict[str, str] = {}
    for n, (key, slug) in enumerate(
        (
            ("README", "README"),
            ("QUEUE", "QUEUE"),
            ("queue", "queue"),
            ("archive", "_archive"),
            ("old", "old"),
            ("hidden", ".hidden"),
            ("result", "old.result-1.1"),
        )
    ):
        repo.write("f.txt", f"{n}\n")
        shas[key] = repo.commit(_msg(f"feat: {key}", f"Task: {slug}#1.1"))
    repo.git("rm", "-q", "-r", "plans/2026-09-01_old", "plans/.hidden", "plans/old.result-1.1.md")
    repo.commit("R remove old")

    doc = _doc(repo, atlas, "main")
    expected = [
        ("REF_TO_MISSING", "blocking", f"commit:{shas[key]}", f"{slug}#1.1", shas[key], _PLAN_GONE.format(slug))
        for key, slug in (
            ("README", "README"),
            ("QUEUE", "QUEUE"),
            ("queue", "queue"),
            ("archive", "_archive"),
            ("hidden", ".hidden"),
            ("result", "old.result-1.1"),
        )
    ]
    expected.append(("REF_MOVED", "info", f"commit:{shas['old']}", "old#1.1", shas["old"], _PLAN_MOVED.format("old")))
    assert _ref_findings(doc) == sorted(expected)


def test_trailers_of_non_merge_ancestors_only(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "non_merge_only")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]", "1.2: second [PENDING]"))
    repo.commit("plan")
    repo.git("checkout", "-q", "-b", "side")
    repo.write("s.txt", "S\n")
    s = repo.commit(_msg("feat: side", "Task: alpha#1.1", "Refs: plans/typo.md"))
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", _msg("Merge side", "Task: alpha#1.2", "Refs: plans/typo2.md"), "side")
    m = repo.head
    assert len(repo.git("rev-list", "--parents", "-n", "1", m).split()) == 3  # M — слияние (2 родителя)

    doc = _doc(repo, atlas, "main", "main")
    assert s in _ids(doc, "commit")  # коммит с трейлером вне прежнего набора получает узел (1.3c р.2)
    assert m in _ids(doc, "commit")  # слияние на first-parent: узел как прежний набор, но без рёбер
    assert _edges(doc, "implements") == [(f"commit:{s}", "task:alpha#1.1", "trailer:Task")]
    assert _edges(doc, "refs") == [(f"commit:{s}", "plan:typo", "trailer:Refs")]
    assert _ref_findings(doc) == [
        ("REF_TO_MISSING", "blocking", f"commit:{s}", "plans/typo.md", s, _PATH_GONE.format("plans/typo.md"))
    ]
    assert _edges(doc, "implements", f"commit:{m}") == []
    assert _edges(doc, "refs", f"commit:{m}") == []


def test_fast_forward_onto_merge_main_into_branch_keeps_side_trailers(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "ff_merge_main")
    repo.write(_PLAN_ALPHA, _plan("1.1: a [PENDING]", "1.2: b [PENDING]", "1.3: c [PENDING]"))
    repo.write("f.txt", "0\n")
    repo.write("g.txt", "0\n")
    repo.commit("m0")
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("f.txt", "1\n")
    f1 = repo.commit(_msg("feat: f1", "Task: alpha#1.1", "Refs: plans/typo.md"))
    repo.write("f.txt", "2\n")
    f2 = repo.commit("feat: f2")
    repo.git("checkout", "-q", "main")
    repo.write("g.txt", "1\n")
    m1 = repo.commit(_msg("feat: m1", "Task: alpha#1.2", "Refs: plans/typo3.md"))
    repo.git("checkout", "-q", "feat")
    repo.git("merge", "-q", "-m", _msg("Merge main into feat", "Task: alpha#1.3", "Refs: plans/typo4.md"), "main")
    mf = repo.head
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--ff-only", "feat")
    assert repo.head == mf
    first_parent = repo.git("rev-list", "--first-parent", "main").split()
    assert first_parent[:3] == [mf, f2, f1]
    assert m1 not in first_parent  # оракул: m1 остался на втором родителе Mf

    doc = _doc(repo, atlas, "main", "main")
    assert m1 in _ids(doc, "commit")  # трейлерный коммит вне first-parent получает узел (1.3c р.2)
    assert mf in _ids(doc, "commit")  # слияние на first-parent: узел есть, рёбер refs/implements нет
    assert f2 in _ids(doc, "commit")
    assert _edges(doc, "implements") == sorted(
        [
            (f"commit:{m1}", "task:alpha#1.2", "trailer:Task"),
            (f"commit:{f1}", "task:alpha#1.1", "trailer:Task"),
        ]
    )
    assert _edges(doc, "refs") == sorted(
        [
            (f"commit:{m1}", "plan:typo3", "trailer:Refs"),
            (f"commit:{f1}", "plan:typo", "trailer:Refs"),
        ]
    )
    assert _ref_findings(doc) == sorted(
        [
            ("REF_TO_MISSING", "blocking", f"commit:{m1}", "plans/typo3.md", m1, _PATH_GONE.format("plans/typo3.md")),
            ("REF_TO_MISSING", "blocking", f"commit:{f1}", "plans/typo.md", f1, _PATH_GONE.format("plans/typo.md")),
        ]
    )
    assert _edges(doc, "touches", f"commit:{m1}") == []
    for key in (mf,):
        assert _edges(doc, "implements", f"commit:{key}") == []
        assert _edges(doc, "refs", f"commit:{key}") == []


def test_pinned_on_a5ae9657a(atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = _real_doc(atlas, monkeypatch, tmp_path, _PIN_A5)
    assert {kind: len(_ids(doc, kind)) for kind in ("commit", "module", "plan", "task")} == {
        "commit": 4656,
        "module": 87,
        "plan": 148,
        "task": 1242,
    }
    assert {kind: len(_edges(doc, kind)) for kind in ("refs", "implements", "touches", "done_by")} == {
        "refs": 4158,
        "implements": 176,
        "touches": 5205,
        "done_by": 313,
    }
    assert sum(1 for _, dst, _ in _edges(doc, "touches") if dst == "module:other") == 2008
    assert _no_bad_chars_in_refs(doc) == []
    assert _dangling_refs(doc) == 140
    findings = doc["findings"]
    codes = [f["code"] for f in findings]
    assert {
        c: codes.count(c)
        for c in (
            "DONE_WITHOUT_COMMIT",
            "COMMIT_WITHOUT_DONE",
            "DONE_HASH_NOT_IN_MAIN",
            "PLAN_SLUG_COLLISION",
            "REF_TO_MISSING",
            "REF_MOVED",
        )
    } == {
        "DONE_WITHOUT_COMMIT": 314,
        "COMMIT_WITHOUT_DONE": 6,
        "DONE_HASH_NOT_IN_MAIN": 0,
        "PLAN_SLUG_COLLISION": 0,
        "REF_TO_MISSING": 59,
        "REF_MOVED": 1076,
    }
    missing = [f for f in findings if f["code"] == "REF_TO_MISSING"]
    moved = [f for f in findings if f["code"] == "REF_MOVED"]
    assert {f["severity"] for f in missing} == {"blocking"}
    assert {f["severity"] for f in moved} == {"info"}
    assert len({f["detail"] for f in moved}) == 101
    assert len({f["detail"] for f in missing}) == 20
    _assert_task_findings_missing(doc)
    pairs = {(f["code"], f["node"], f["detail"]) for f in findings}
    assert (
        "REF_TO_MISSING",
        "commit:06d8789cd9d12b1361b11c3c3f910181026fa19e",
        "plans/processes-workers-runtime.md",
    ) in pairs
    assert (
        "REF_MOVED",
        "commit:00781adb4157ac425ef2624bd57564905a201cf4",
        "plans/2026-06-06_command-result-bridge/plan.md",
    ) in pairs
    first_parent = _sha_set(["rev-list", "--first-parent", _PIN_A5])
    assert sum(1 for f in moved if f["node"].removeprefix("commit:") not in first_parent) == 511
    assert sum(1 for f in missing if "#" not in f["detail"] and f["source"] not in first_parent) == 4

    # оракул implements: различные (коммит, значение Task) среди коммитов без слияний, значение с `#`
    raw = GitRepo(_ROOT).git("log", "--no-merges", "--format=\x01%H\x02%B", _PIN_A5)
    oracle: set[tuple[str, str]] = set()
    for entry in raw.split("\x01"):
        if not entry.strip():
            continue
        sha, body = entry.split("\x02", 1)
        for value in re.findall(r"^Task:[ \t]*(\S.*?)[ \t\r]*$", body, re.MULTILINE):
            left, hash_sign, right = value.partition("#")
            if hash_sign and left and right:
                oracle.add((sha.strip(), value))
    implements = _edges(doc, "implements")
    assert len(implements) == len(oracle) == 176
    assert sum(1 for sha, _ in oracle if sha not in first_parent) == 176
    _assert_no_orphan_refs(doc)


def test_commits_adapter_version_is_bumped() -> None:
    from scripts.atlas.adapters.commits import CommitsAdapter
    from scripts.atlas.adapters.plans import PlansAdapter

    assert CommitsAdapter().version >> 48 == 4
    assert PlansAdapter().version >> 48 == 2


def test_commit_nodes_for_trailer_commits_on_temp_repo(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "trailer_nodes")
    repo.write(_PLAN_ALPHA, _plan("1.1: first [PENDING]"))
    m0 = repo.commit("m0")
    repo.git("checkout", "-q", "-b", "side")
    repo.write("s.txt", "1\n")
    s1 = repo.commit(_msg("feat: s1", "Task: alpha#1.1"))
    repo.write("s.txt", "2\n")
    s2 = repo.commit(_msg("feat: s2", "Refs: docs/x.md"))
    repo.write("s.txt", "3\n")
    s3 = repo.commit("feat: s3")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", _msg("Merge side", "Refs: plans/typo.md"), "side")
    mg = repo.head
    assert repo.git("rev-list", "--first-parent", "main").split() == [mg, m0]

    doc = _doc(repo, atlas, "main", "main")
    ids = set(_ids(doc, "commit"))
    assert {s1, s2, mg, m0} <= ids
    assert s3 not in ids  # нет трейлера и вне прежнего набора
    for src, _, _ in _edges(doc, "refs") + _edges(doc, "implements"):
        assert src.removeprefix("commit:") in ids
    assert _edges(doc, "implements") == [(f"commit:{s1}", "task:alpha#1.1", "trailer:Task")]
    assert _edges(doc, "refs") == []  # у S2 значение вне plans/, трейлеры слияния Mg не читаются
    assert _edges(doc, "touches", f"commit:{s1}") == []
    node_s1 = next(n for n in doc["nodes"] if n["kind"] == "commit" and n["id"] == s1)
    assert node_s1["path"] is None
    assert node_s1["status"] is None
    assert node_s1["time"] == int(repo.git("log", "-1", "--format=%ct", s1))


def _load_plans_progress() -> Any:
    path = _ROOT / "scripts" / "plans_progress" / "plans_progress.py"
    name = "_atlas_test_plans_progress"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def test_service_name_constant_matches_plans_progress() -> None:
    from scripts.atlas.adapters import commits

    plans_progress = _load_plans_progress()
    listing = GitRepo(_ROOT).git("ls-tree", "--name-only", "HEAD", "plans/", "plans/_archive/")
    clone_names = {line.rsplit("/", 1)[-1] for line in listing.splitlines() if line}
    names = set(clone_names)
    # предусловие осмысленности: хотя бы одно имя из `git ls-tree` клона (до синтетики) служебное (README.md)
    assert any(commits._is_service_name(n) for n in clone_names)
    names |= {
        ".hidden",
        "x.result-1.1.md",
        "a.result-.md",
        "result-1.md",
        "Readme.md",
        "readme.md",
        "queue",
        "queues",
        "_archive",
        "QUEUE.md",
        "plan.md",
        "2026-10-01_alpha",
        "README.md",
    }
    for name in sorted(names):
        assert commits._is_service_name(name) == plans_progress.is_service_name(name), name
    # литеральные пины источника: добавление имени в plans_progress краснит тест, даже если файла в plans/ нет
    assert plans_progress.SERVICE_NAMES == {"queue", "_archive", "QUEUE.md", "README.md"}
    assert plans_progress.RESULT_FILE_RE.pattern == r"\.result-.+\.md$"
    assert commits._SERVICE_NAMES == {"queue", "_archive", "QUEUE.md", "README.md"}
