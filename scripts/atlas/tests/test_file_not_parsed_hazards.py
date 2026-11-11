"""Hazard-тесты находки FILE_NOT_PARSED: границы охвата `ParseAdapter` (Task B7, автор — исполнитель).

Purpose: добавляют к слепым приёмочным тестам две границы, которые мутанты `parse.py` иначе проходят незамеченными:
    не-.py файлы в охваченном юните не читаются как исходник; строка другого слоя, вложенная в юнит framework
    (самый длинный префикс `paths`), выводит свои файлы из охвата. Фикстуры и помощники — из test_file_not_parsed.
Public API: нет (только test_*).
Stability: lite
"""

from __future__ import annotations

from scripts.atlas.tests.test_file_not_parsed import BROKEN, VALID, _check, _new, _put

__all__: list[str] = []


def test_non_py_files_in_a_covered_unit_are_not_parsed(repo_factory, atlas):
    repo = _new(repo_factory, "h1", [("m", "framework")], {"m/x.py": VALID})
    _put(repo, "m/README.md", "Проза, а не код: это описание модуля.\n")  # не Python: SyntaxError при разборе
    _put(repo, "m/data.json", '{"a": 1}\n')  # валидный JSON
    _put(repo, "m/notes.txt", "just some notes, not code\n")  # не Python: SyntaxError при разборе
    _put(repo, "m/x.py", BROKEN)  # якорь: единственная ожидаемая находка
    repo.commit("feat: break x.py, add non-py files")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/x.py SyntaxError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]


def test_nested_prototype_row_inside_a_framework_unit_is_out_of_scope(repo_factory, atlas):
    repo = _new(
        repo_factory,
        "h2",
        [("m", "framework"), ("m/proto", "prototype")],
        {"m/x.py": VALID, "m/proto/z.py": VALID},
    )
    _put(repo, "m/x.py", BROKEN)  # layer framework: в охвате
    _put(repo, "m/proto/z.py", BROKEN)  # самый длинный префикс — строка слоя prototype: вне охвата
    repo.commit("feat: break both")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/x.py SyntaxError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]
