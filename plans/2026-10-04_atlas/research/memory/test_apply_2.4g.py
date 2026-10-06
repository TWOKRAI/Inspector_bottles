"""Тесты одноразового `apply_2.4g.py` на одноразовом git-репо в tmp_path.

Запуск — явным путём (в `testpaths` не входит; имя с точкой требует importlib-режима):
    pytest plans/2026-10-04_atlas/research/memory/test_apply_2.4g.py --import-mode=importlib -q -p no:cacheprovider
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TOOL = HERE / "apply_2.4g.py"
SCRIPTS_MEMORY = HERE.parents[3] / "scripts" / "memory"
sys.path.insert(0, str(SCRIPTS_MEMORY))

import _lessons  # noqa: E402

MEM = "docs/claude/memory"
ROLE = ".claude/agent-memory"
BODY = (
    b"\nBody line.\n---\nmodule: from_body\n\xd1\x82\xd0\xb5\xd0\xbb\xd0\xbe \xe2\x86\x92 \r\ntail with spaces  \n\n \n"
)


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Fixture"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "fixture@example.invalid"
    return env


def _git(tmp_path: Path, root: Path, *args: str) -> str:
    cp = subprocess.run(  # nosec B603 B607
        ["git", "-c", "init.defaultBranch=main", *args], cwd=root, env=_env(tmp_path), capture_output=True
    )
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    return cp.stdout.decode("utf-8", "replace")


def _write(root: Path, rel: str, data: bytes | str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def _lesson(name: str, *lines: str, eol: str = "\n", body: bytes = BODY) -> bytes:
    head = eol.join(["---", f"name: {name}", *lines, "---"]) + eol
    return head.encode("utf-8") + body


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write(root, "modules.yaml", "modules:\n  - id: logger_module\n  - id: frontend_module\n")
    _write(
        root,
        f"{MEM}/TAGS.yaml",
        'mechanisms:\n  - id: break-injection\n    def: "d"\n  - id: fixture-trap\n    def: "d"\n',
    )
    _write(root, f"{MEM}/MEMORY.md", "# index\n")
    _write(root, ".claude/agents/dev/tester.md", "# tester\n")
    _write(root, ".claude/agents/dev/developer.md", "# developer\n")
    _write(root, f"{ROLE}/tester/MEMORY.md", "old one\nold two\nold three\nold four\nold five\n")
    _write(root, f"{ROLE}/developer/MEMORY.md", "old\n")
    _write(root, f"{ROLE}/tester/role_lesson.md", _lesson("role-lesson", "description: старое описание"))
    _write(
        root,
        f"{MEM}/canon_lesson.md",
        _lesson(
            "canon-lesson",
            "description: old canon desc",
            "module: old_module",
            "metadata:",
            "  type: feedback",
            "  module: nested_old",
            "  mechanism: [nested_mech]",
        ),
    )
    _write(root, f"{MEM}/crlf_lesson.md", _lesson("crlf-lesson", "description: old", "module: m", eol="\r\n"))
    _git(tmp_path, root, "init", "-q")
    _git(tmp_path, root, "add", "-A")
    _git(tmp_path, root, "commit", "-q", "-m", "fixture")
    return root


def _tsv(tmp_path: Path, *rows: tuple) -> Path:
    p = tmp_path / "rows.tsv"
    p.write_bytes(
        ("file\tmodule\tmechanism\tdescription\n" + "".join("\t".join(r) + "\n" for r in rows)).encode("utf-8")
    )
    return p


def _coll(tmp_path: Path, *rows: tuple[Path, Path]) -> Path:
    p = tmp_path / "collisions.tsv"
    p.write_bytes(("loser\twinner\n" + "".join(f"{a}\t{b}\n" for a, b in rows)).encode("utf-8"))
    return p


def _run(tmp_path: Path, root: Path, tsv: Path, *extra: str):
    cp = subprocess.run(  # nosec B603
        [sys.executable, str(TOOL), "--root", str(root), "--tsv", str(tsv), *extra],
        cwd=root,
        env=_env(tmp_path),
        capture_output=True,
        timeout=120,
    )
    return cp.returncode, cp.stdout.decode("utf-8"), cp.stderr.decode("utf-8", "replace")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
    }


def _body(data: bytes) -> bytes:
    """Всё после закрывающей `---` (проверено на синтетике, как команда A3.5)."""
    lines = data.split(b"\n")
    fences = [i for i, ln in enumerate(lines) if ln.rstrip(b"\r") == b"---"]
    return b"\n".join(lines[fences[1] + 1 :])


def test_role_lesson_moved_tagged_with_role_and_body_unchanged(tmp_path, repo):
    src = repo / ROLE / "tester" / "role_lesson.md"
    original = src.read_bytes()
    rc, out, err = _run(
        tmp_path, repo, _tsv(tmp_path, (str(src), "logger_module, frontend_module", "break-injection", "Тест test"))
    )
    assert rc == 0, (out, err)
    dst = repo / MEM / "role_lesson.md"
    assert not src.exists() and dst.is_file()
    assert _body(dst.read_bytes()) == _body(original)
    fm = _lessons.parse_frontmatter(dst.read_bytes().decode("utf-8"))
    assert fm["module"] == ["logger_module", "frontend_module"]
    assert fm["mechanism"] == ["break-injection"]
    assert fm["role"] == ["tester"]
    assert fm["description"] == ["Тест test"]
    assert fm["name"] == ["role-lesson"]
    # git mv, а не удаление + создание: индекс видит переименование (R), затем правка frontmatter (M)
    status = _git(tmp_path, repo, "status", "--short")
    assert "RM .claude/agent-memory/tester/role_lesson.md -> docs/claude/memory/role_lesson.md" in status


def test_canon_lesson_retagged_in_place_old_tags_removed(tmp_path, repo):
    path = repo / MEM / "canon_lesson.md"
    original = path.read_bytes()
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, (str(path), "", "fixture-trap", "Новое new")))
    assert rc == 0, (out, err)
    data = path.read_bytes()
    text = data.decode("utf-8")
    assert _body(data) == _body(original)
    fm = _lessons.parse_frontmatter(text)
    assert fm["module"] == []  # пустой module: строки нет, старые теги (верх и metadata) убраны
    assert fm["mechanism"] == ["fixture-trap"]
    assert fm["role"] == []
    assert fm["description"] == ["Новое new"]
    for gone in ("old_module", "nested_old", "nested_mech", "old canon desc"):
        assert gone not in text.split("\n---\n")[0]
    head = text.split("---")[1]
    assert "metadata:\n  type: feedback\n" in head  # прочие ключи на месте
    assert head.index("name:") < head.index("description:") < head.index("metadata:")
    assert "module:" not in head


def test_crlf_file_stays_crlf(tmp_path, repo):
    path = repo / MEM / "crlf_lesson.md"
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, (str(path), "logger_module", "break-injection", "Тест test")))
    assert rc == 0, (out, err)
    data = path.read_bytes()
    head = data[: data.index(b"---", 4) + 3]
    assert b"\n" not in head.replace(b"\r\n", b"")  # ни одного голого \n во frontmatter
    assert head.count(b"\r\n") == head.count(b"\n")
    assert _body(data) == _body(_lesson("x", eol="\r\n"))


def test_collision_loser_archived_winner_gets_merged_from(tmp_path, repo):
    loser = repo / ROLE / "tester" / "role_lesson.md"
    winner = repo / MEM / "canon_lesson.md"
    loser_stem_bytes = loser.read_bytes()
    rc, out, err = _run(
        tmp_path,
        repo,
        _tsv(
            tmp_path,
            (str(winner), "logger_module", "break-injection", "Победитель winner"),
            (str(loser), "", "fixture-trap", "Игнор ignore"),
        ),
        "--collisions",
        str(_coll(tmp_path, (loser, winner))),
    )
    assert rc == 0, (out, err)
    archived = repo / MEM / "_archive" / "role_lesson.md"
    assert archived.read_bytes() == loser_stem_bytes  # проигравший не тронут и не размечен
    assert not loser.exists() and not (repo / MEM / "role_lesson.md").exists()
    text = winner.read_bytes().decode("utf-8")
    assert "merged_from: [role_lesson]" in text
    assert _lessons.parse_frontmatter(text)["mechanism"] == ["break-injection"]  # строка TSV победителя применена
    assert "SKIP" in out


def test_collision_archive_name_taken_gets_role_suffix(tmp_path, repo):
    _write(repo, f"{MEM}/_archive/role_lesson.md", "already here\n")
    loser = repo / ROLE / "tester" / "role_lesson.md"
    winner = repo / MEM / "canon_lesson.md"
    rc, out, err = _run(
        tmp_path,
        repo,
        _tsv(tmp_path, (str(winner), "logger_module", "break-injection", "Победитель winner")),
        "--collisions",
        str(_coll(tmp_path, (loser, winner))),
    )
    assert rc == 0, (out, err)
    assert (repo / MEM / "_archive" / "role_lesson-tester.md").is_file()
    assert (repo / MEM / "_archive" / "role_lesson.md").read_bytes() == b"already here\n"


@pytest.mark.parametrize(
    "row",
    [
        ("{canon}", "logger_module", "no-such-mech", "Тест test"),
        ("{canon}", "no_such_module", "break-injection", "Тест test"),
        ("{canon}", "logger_module", "break-injection", "bad\tdescription"),
        ("{outside}", "logger_module", "break-injection", "Тест test"),
        ("{missing}", "logger_module", "break-injection", "Тест test"),
    ],
    ids=["unknown-mechanism", "unknown-module", "tab-in-description", "outside-root", "missing-file"],
)
def test_refusal_exits_2_and_changes_nothing(tmp_path, repo, row):
    outside = tmp_path / "outside.md"
    outside.write_bytes(_lesson("out"))
    path = repo / MEM / "canon_lesson.md"
    good = (
        str(repo / ROLE / "tester" / "role_lesson.md"),
        "logger_module",
        "break-injection",
        "Тест test",
    )  # до плохой
    bad = tuple(c.format(canon=path, outside=outside, missing=repo / MEM / "nope.md") for c in row)
    before = _snapshot(repo)
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, good, bad))
    assert rc == 2, (out, err)
    assert "refused" in err
    assert _snapshot(repo) == before
    assert _git(tmp_path, repo, "status", "--short") == ""


def test_missing_tsv_exits_2(tmp_path, repo):
    rc, out, err = _run(tmp_path, repo, tmp_path / "nope.tsv")
    assert rc == 2 and "TSV" in err


def test_dry_run_changes_nothing_and_prints_plan(tmp_path, repo):
    rows = (
        (str(repo / ROLE / "tester" / "role_lesson.md"), "logger_module", "break-injection", "Тест test"),
        (str(repo / MEM / "canon_lesson.md"), "", "fixture-trap", "Новое new"),
        (str(repo / MEM / "crlf_lesson.md"), "frontend_module", "", "Крлф crlf"),
    )
    before = _snapshot(repo)
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, *rows), "--dry-run")
    assert rc == 0, (out, err)
    assert _snapshot(repo) == before
    assert _git(tmp_path, repo, "status", "--short") == ""
    lines = out.splitlines()
    assert sum(ln.startswith("MOVE+RETAG ") for ln in lines) == 1
    assert sum(ln.startswith("RETAG ") for ln in lines) == 2
    assert "dry-run: nothing changed" in out
    assert "tags.py --check" not in out  # проверка тегов на сухом прогоне не запускается
    print(out)


def test_role_memory_md_is_exactly_three_lines(tmp_path, repo):
    path = repo / MEM / "canon_lesson.md"
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, (str(path), "logger_module", "", "Тест test")))
    assert rc == 0, (out, err)
    for role in ("tester", "developer"):
        text = (repo / ROLE / role / "MEMORY.md").read_bytes().decode("utf-8")
        assert text == (
            "Lessons of every role live in docs/claude/memory/ (main checkout); this directory holds no lessons.\n"
            'Search: python "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/memory/search.py" <3-5 words>\n'  # noqa: E501
            "New lesson: a MEMORY LESSON <name>.md block in your final report; the lead files it.\n"
        )


def test_description_quotes_and_backslashes_are_escaped(tmp_path, repo):
    path = repo / MEM / "canon_lesson.md"
    desc = 'the "gorynych" path C:\\x, with: colon'
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, (str(path), "logger_module", "", desc)))
    assert rc == 0, (out, err)
    text = path.read_bytes().decode("utf-8")
    assert 'description: "the \\"gorynych\\" path C:\\\\x, with: colon"' in text
    assert _lessons.parse_frontmatter(text)["description"] == [desc]


def test_multiline_description_and_block_list_are_removed_with_their_continuation(tmp_path, repo):
    path = _write(
        repo,
        f"{MEM}/block_lesson.md",
        _lesson(
            "block",
            "description: first line",
            "  continued line: with colon",
            "module:",
            "  - old_a",
            "  - old_b",
            "type: keep",
        ),
    )
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, (str(path), "logger_module", "", "Новое new")))
    assert rc == 0, (out, err)
    text = path.read_bytes().decode("utf-8")
    assert "continued line" not in text and "old_a" not in text and "old_b" not in text
    assert "type: keep" in text
    assert _lessons.parse_frontmatter(text)["module"] == ["logger_module"]


def test_check_result_is_printed_as_information(tmp_path, repo):
    path = repo / MEM / "canon_lesson.md"
    rc, out, err = _run(tmp_path, repo, _tsv(tmp_path, (str(path), "logger_module", "", "Тест test")))
    assert rc == 0, (out, err)
    assert "tags.py --check exit code: " in out
