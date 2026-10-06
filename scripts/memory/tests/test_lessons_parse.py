"""Авторские тесты разбора frontmatter (2.4g.1): края, которые слепая приёмка не фиксирует.

Решение по BOM: ведущий BOM снимается, файл с BOM и `---` первой строкой — урок с frontmatter.
Решение по незакрытому frontmatter: нет закрывающей `---` — frontmatter нет (`{}`), урок получает no-tag.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
