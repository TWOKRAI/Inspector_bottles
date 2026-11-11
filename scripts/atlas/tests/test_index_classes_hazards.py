"""Hazard-тесты строки `классы:` вида `index`: границы охвата `_public_classes` (Task IDX1, автор — исполнитель).

Purpose: добавляют к слепым приёмочным тестам три границы, которые мутанты `reference._public_classes` иначе проходят
    незамеченными: не-.py файлы юнита не читаются как исходник; строка другого слоя, вложенная в юнит framework
    (самый длинный префикс `paths`), выводит свои файлы из охвата; файл, на котором `ast.parse` бросает не
    SyntaxError (RecursionError), пропускается, а `index` не падает. Фикстуры и помощники — из test_index_classes.
Public API: нет (только test_*).
Stability: lite
"""

from __future__ import annotations

from scripts.atlas.tests.test_index_classes import _HEADER, _NO_PURPOSE, _cls, _index, _m, _one_unit, _repo

__all__: list[str] = []


def test_non_py_files_in_a_unit_are_not_read_as_source(repo_factory, atlas):
    repo = _one_unit(
        repo_factory,
        "h1",
        {
            "m/notes.txt": "class NotPy:\n    pass\n",  # валидный Python по содержимому, но не .py
            "m/readme.md": "class InReadme:\n    pass\n",
            "m/stub.pyi": "class Pyi: ...\n",  # .pyi — не .py
            "m/x.py": "class Keep: ...\n",  # якорь
        },
    )
    assert _index(atlas, repo) == _m(_cls("Keep"))


def test_nested_prototype_row_inside_a_framework_unit_gives_no_classes(repo_factory, atlas):
    repo = _repo(
        repo_factory,
        "h2",
        [("m", ["m/"], "framework"), ("m/proto", ["m/proto/"], "prototype")],
        {"m/x.py": "class Keep: ...\n", "m/proto/z.py": "class Hidden: ...\n"},
    )
    assert _index(atlas, repo) == [
        _HEADER,
        f"m — {_NO_PURPOSE}",
        _cls("Keep"),
        f"m/proto — {_NO_PURPOSE}",
    ]


def test_file_that_raises_recursion_error_in_ast_parse_is_skipped(repo_factory, atlas):
    deep = "x = " + "+".join(["1"] * 200_000) + "\n"  # ~400 КБ < MAX_BLOB_BYTES; ast.parse -> RecursionError
    repo = _one_unit(repo_factory, "h3", {"m/deep.py": deep, "m/x.py": "class Keep: ...\n"})
    assert _index(atlas, repo) == _m(_cls("Keep"))  # _index проверяет exit 0
