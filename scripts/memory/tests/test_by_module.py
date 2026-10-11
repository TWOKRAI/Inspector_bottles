"""Hazard-тесты 2.4j: функции `by_module.py` напрямую (слепой файл ходит только через CLI).

Ожидаемые значения — литералы. Файлы пишутся в tmp, дерево репозитория не трогается.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_MEMORY = Path(__file__).resolve().parents[1]


def _load(name: str):
    if str(SCRIPTS_MEMORY) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_MEMORY))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_MEMORY / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load("by_module")
lessons = _load("_lessons")

MEM = "docs/claude/memory"


def _lesson(root: Path, name: str, text: str) -> None:
    p = root / MEM / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


@pytest.mark.parametrize(
    ("module", "layer"),
    [
        ("services", "services"),
        ("services/x", "services"),
        ("plugins", "plugins"),
        ("plugins_shared", "plugins"),
        ("prototype", "prototype"),
        ("tools", "tools"),
        ("scripts/atlas", "tools"),
        ("frontend_module/widgets", "framework"),
        ("process_module/generic", "framework"),
        ("framework_meta", "framework"),
        ("servicesX", "framework"),  # сегмент сравнивается целиком, не префиксом
        ("pluginsfoo/plugins", "framework"),  # слой — по первому сегменту
        ("", "framework"),
    ],
)
def test_layer_of_table(module, layer):
    assert bm.layer_of(module) == layer


@pytest.mark.parametrize(
    ("desc", "expected"),
    [
        ([], ""),
        (["a", "b"], "a b"),  # многострочное описание склеивается одним пробелом
        (["x" * 80], "x" * 80),
        (["x" * 81], "x" * 79 + "…"),
        (["y" * 79 + " "], "y" * 79 + " "),  # без rstrip: пробел на границе остаётся
    ],
)
def test_short_description(desc, expected):
    assert bm.short_description({"description": desc}) == expected


def test_short_description_without_frontmatter_is_empty():
    assert bm.short_description({}) == ""


def test_description_with_pipe_does_not_break_hub_table(tmp_path):
    # `|` в описании живёт только в строках слоя, не в таблице хаба
    _lesson(tmp_path, "p.md", "---\nname: p\ndescription: a | b\nmodule: tools\nmechanism: m\n---\n")
    files = bm.generate(bm.collect(tmp_path))
    assert "- [p](p.md) — a | b" in files["BY-MODULE-tools.md"].split("\n")
    assert "| tools | [BY-MODULE-tools.md](BY-MODULE-tools.md) | 1 | 1 |" in files["BY-MODULE.md"]


def test_duplicate_module_values_count_lesson_once(tmp_path):
    # parse_frontmatter убирает дубли значений: урок не должен стоять в разделе дважды
    _lesson(tmp_path, "d.md", "---\nname: d\ndescription: d\nmodule: [tools, tools]\nmechanism: m\n---\n")
    layer = bm.generate(bm.collect(tmp_path))["BY-MODULE-tools.md"]
    assert layer.count("- [d](d.md)") == 1
    assert "## tools (1)" in layer


def test_run_write_creates_missing_memory_dir_only_for_index(tmp_path):
    assert bm.run(tmp_path, write=True) == 0
    names = sorted(p.name for p in (tmp_path / MEM).iterdir())
    assert names == ["BY-MODULE-mechanism.md", "BY-MODULE.md"]  # без уроков: хаб + пустой mechanism
    assert bm.run(tmp_path, write=False) == 0


def test_run_check_on_missing_memory_dir_reports_missing_not_crash(tmp_path, capsys):
    assert bm.run(tmp_path, write=False) == 1
    assert capsys.readouterr().out.split("\n")[:2] == ["missing: BY-MODULE-mechanism.md", "missing: BY-MODULE.md"]


def test_too_big_refuses_both_modes_and_keeps_disk(tmp_path, capsys, monkeypatch):
    _lesson(tmp_path, "a.md", "---\nname: a\ndescription: a\nmodule: tools\nmechanism: m\n---\n")
    monkeypatch.setattr(bm, "MAX_FILE_BYTES", 10)
    assert bm.run(tmp_path, write=True) == 2
    assert bm.run(tmp_path, write=False) == 2
    err = capsys.readouterr().err
    assert err.startswith("too big: BY-MODULE-mechanism.md ")
    assert sorted(p.name for p in (tmp_path / MEM).iterdir()) == ["a.md"]


def test_generated_text_is_lf_only_with_single_final_newline(tmp_path):
    _lesson(tmp_path, "a.md", "---\r\nname: a\r\ndescription: а\r\nmodule: tools\r\nmechanism: m\r\n---\r\nbody\r\n")
    for name, text in bm.generate(bm.collect(tmp_path)).items():
        assert "\r" not in text, name
        assert text.endswith("\n") and not text.endswith("\n\n"), name


def test_iter_lessons_skips_by_module_prefix(tmp_path):
    for name in ("BY-MODULE.md", "BY-MODULE-x.md", "BY-MODULEfoo.md", "by-module-lower.md", "real.md"):
        _lesson(tmp_path, name, "---\nname: n\n---\n")
    assert [p.name for p in lessons.iter_lessons(tmp_path / MEM)] == ["by-module-lower.md", "real.md"]
