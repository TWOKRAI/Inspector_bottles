"""Авторские тесты разбора frontmatter (2.4g.1): края, которые слепая приёмка не фиксирует.

Решение по BOM: ведущий BOM снимается, файл с BOM и `---` первой строкой — урок с frontmatter.
Решение по незакрытому frontmatter: нет закрывающей `---` — frontmatter нет (`{}`), урок получает no-tag.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _lessons  # noqa: E402


def parse(*lines: str, body: str = "Body.\n") -> dict[str, list[str]]:
    return _lessons.parse_frontmatter("---\n" + "\n".join(lines) + "\n---\n" + body)


def test_body_dash_line_not_frontmatter():
    # `---` в теле после frontmatter не открывает второй блок: ключи из тела не читаются
    fm = parse("name: x", "module: a", body="text\n---\nmodule: from_body\n---\n")
    assert fm["module"] == ["a"]


def test_second_dash_line_closes_frontmatter_early():
    # контроль к предыдущему: ключ ПОСЛЕ первой закрывающей `---` не попадает в frontmatter
    text = "---\nmodule: a\n---\nmodule: late\n"
    assert _lessons.parse_frontmatter(text)["module"] == ["a"]


def test_metadata_block_ends_at_top_level_key():
    fm = parse("metadata:", "  module: inner", "description: top", "  mechanism: orphan")
    assert fm["module"] == ["inner"]
    # `mechanism` с отступом, но уже вне metadata (блок закрыл top-level `description`) — не читается
    assert fm["mechanism"] == []
    assert fm["description"] == ["top"]


def test_indented_key_outside_metadata_is_ignored():
    fm = parse("other:", "  module: nested_elsewhere")
    assert fm["module"] == []


def test_description_with_colon_space_is_kept_whole():
    fm = parse("description: fixture: a trap, with comma", "module: a")
    assert fm["description"] == ["fixture: a trap, with comma"]
    assert fm["module"] == ["a"]


def test_description_is_not_split_by_commas_but_module_is():
    fm = parse("description: one, two", "module: a, b")
    assert fm["description"] == ["one, two"]
    assert fm["module"] == ["a", "b"]


def test_bom_is_stripped():
    fm = _lessons.parse_frontmatter("﻿---\nmodule: a\n---\n")
    assert fm["module"] == ["a"]


def test_key_with_only_spaces_after_colon_is_absent():
    fm = parse("module:    ", "mechanism:\t", "role: tester")
    assert fm["module"] == []
    assert fm["mechanism"] == []
    assert fm["role"] == ["tester"]


def test_no_frontmatter_returns_empty_dict():
    assert _lessons.parse_frontmatter("module: a\n") == {}
    assert _lessons.parse_frontmatter("") == {}


def test_unclosed_frontmatter_is_no_frontmatter():
    assert _lessons.parse_frontmatter("---\nmodule: a\nno closing fence\n") == {}


def test_empty_frontmatter_has_all_keys_empty():
    fm = _lessons.parse_frontmatter("---\n---\n")
    assert fm == {k: [] for k in ("name", "description", "module", "mechanism", "role")}


def test_same_key_top_level_and_metadata_is_union_without_duplicates():
    fm = parse("module: a, b", "metadata:", "  module: [b, c]")
    assert fm["module"] == ["a", "b", "c"]


def test_crlf_and_quoted_list_forms():
    text = '---\r\nmodule: ["a", \'b\']\r\nmechanism: "x"\r\n---\r\n'
    fm = _lessons.parse_frontmatter(text)
    assert fm["module"] == ["a", "b"]
    assert fm["mechanism"] == ["x"]


def test_iter_lessons_excludes_non_lessons_and_subdirs(tmp_path):
    for name in ("a.md", "b.md", "MEMORY.md", "ARCHIVE.md", "CRAFT-tests.md", "notes.txt"):
        (tmp_path / name).write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.md").write_text("x")
    assert [p.name for p in _lessons.iter_lessons(tmp_path)] == ["a.md", "b.md"]


# --------------------------------------------------------------------------- review round 1: parse


def test_quoted_whole_list_value_is_unquoted_then_split():
    fm = parse('module: "telemetry, config.reload"', 'mechanism: "a, b"')
    assert fm["module"] == ["telemetry", "config.reload"]
    assert fm["mechanism"] == ["a", "b"]


def test_quoted_description_with_comma_stays_one_string():
    assert parse('description: "x, y"')["description"] == ["x, y"]


def test_double_quoted_description_unescapes_backslash_quote():
    assert parse(r'description: "the \"gorynych\" trap"')["description"] == ['the "gorynych" trap']


def test_single_quoted_description_keeps_backslashes():
    assert parse(r"description: 'a\"b'")["description"] == [r"a\"b"]


# --------------------------------------------------------------------------- review round 1: CLI pins

MEMORY_DIR = Path(__file__).resolve().parents[1]
TAGS_PY = MEMORY_DIR / "tags.py"
SEARCH_PY = MEMORY_DIR / "search.py"
MEM = "docs/claude/memory"
GOOD_DESC = "фикстура fixture"


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _lesson(root: Path, fname: str, *lines: str, desc: str = GOOD_DESC) -> None:
    head = f"---\nname: {fname[:-3]}\ndescription: {desc}\n" + "".join(f"{ln}\n" for ln in lines) + "---\nBody.\n"
    _w(root, f"{MEM}/{fname}", head)


def _make_root(root: Path, *, tags: bool = True) -> Path:
    _w(root, "modules.yaml", "modules:\n  - id: logger_module\n    path: logger_module\n  - id: frontend_module\n")
    _w(root, ".claude/agents/dev/tester.md", "# tester\n")
    if tags:
        _w(root, f"{MEM}/TAGS.yaml", 'mechanisms:\n  - id: break-injection\n    def: "d"\n')
    return root


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Fixture"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "fixture@example.invalid"
    return env


def _run(script: Path, args: list[str], *, cwd: Path, tmp_path: Path):
    cp = subprocess.run(
        [sys.executable, str(script), *args], cwd=str(cwd), env=_env(tmp_path), capture_output=True, timeout=60
    )
    return cp.returncode, cp.stdout.decode("utf-8"), cp.stderr.decode("utf-8", "replace")


def _git(args: list[str], *, cwd: Path, tmp_path: Path) -> None:
    cp = subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args], cwd=str(cwd), env=_env(tmp_path), capture_output=True
    )
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def _init_git(root: Path, tmp_path: Path) -> None:
    _git(["init", "-q"], cwd=root, tmp_path=tmp_path)
    _git(["add", "-A"], cwd=root, tmp_path=tmp_path)
    _git(["commit", "-q", "-m", "fixture"], cwd=root, tmp_path=tmp_path)


def test_quoted_module_list_checked_per_element(tmp_path):
    root = _make_root(tmp_path / "repo")
    _lesson(root, "q.md", 'module: "logger_module, not_a_module"')
    rc, out, _ = _run(TAGS_PY, ["--check", "--root", str(root)], cwd=root, tmp_path=tmp_path)
    assert rc == 1
    assert out.splitlines() == [f"{MEM}/q.md: unknown-module: 'not_a_module'"]


def test_check_without_root_uses_current_worktree_not_main(tmp_path):
    main = _make_root(tmp_path / "main")
    _lesson(main, "good.md", "module: logger_module")
    _init_git(main, tmp_path)
    wt = tmp_path / "wt"
    _git(["worktree", "add", "-q", str(wt), "-b", "side"], cwd=main, tmp_path=tmp_path)
    _lesson(wt, "wt_bad.md", "module: not_a_module")  # only in the worktree
    rc, out, err = _run(TAGS_PY, ["--check"], cwd=wt, tmp_path=tmp_path)
    assert rc == 1, err
    assert out.splitlines() == [f"{MEM}/wt_bad.md: unknown-module: 'not_a_module'"]
    # control: from main the worktree-only lesson is invisible and main is clean
    rc, out, err = _run(TAGS_PY, ["--check"], cwd=main, tmp_path=tmp_path)
    assert (rc, out) == (0, ""), err


def test_missing_tags_yaml_exits_2_and_names_the_file(tmp_path):
    root = _make_root(tmp_path / "repo", tags=False)
    _lesson(root, "good.md", "module: logger_module")
    rc, out, err = _run(TAGS_PY, ["--check", "--root", str(root)], cwd=root, tmp_path=tmp_path)
    assert rc == 2
    assert "TAGS.yaml" in err
    assert out == ""


def test_word_does_not_match_role_tag(tmp_path):
    root = _make_root(tmp_path / "repo")
    _lesson(root, "by_role.md", "module: logger_module", "role: tester")
    _lesson(root, "ctl.md", "module: logger_module", desc="фикстура tester word")  # control: word search is alive
    rc, out, _ = _run(SEARCH_PY, ["tester", "--root", str(root)], cwd=root, tmp_path=tmp_path)
    assert rc == 0
    assert [Path(ln.partition(" — ")[0]).name for ln in out.splitlines()] == ["ctl.md"]


def _nine_lessons(root: Path) -> list[str]:
    names = [f"l{i}.md" for i in range(9)]
    for n in names:
        _lesson(root, n, "module: logger_module")
    return names


@pytest.mark.parametrize("extra", [[], ["--limit", "3"]])
def test_list_prints_all_and_ignores_limit(tmp_path, extra):
    root = _make_root(tmp_path / "repo")
    names = _nine_lessons(root)
    rc, out, _ = _run(SEARCH_PY, ["--list", *extra, "--root", str(root)], cwd=root, tmp_path=tmp_path)
    assert rc == 0
    assert [Path(ln.partition(" — ")[0]).name for ln in out.splitlines()] == names


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_limit_below_one_is_rejected_with_exit_2(tmp_path, limit):
    root = _make_root(tmp_path / "repo")
    _nine_lessons(root)
    rc, out, err = _run(SEARCH_PY, ["fixture", "--limit", limit, "--root", str(root)], cwd=root, tmp_path=tmp_path)
    assert rc == 2, (out, err)
    assert "limit" in err
    assert out == ""
