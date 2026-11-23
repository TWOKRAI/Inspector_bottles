"""Тесты-ловушки `links.bases` (Task 4.1b, автор кода): граничные формы основ, не покрытые приёмочными тестами.

Purpose: вложенные скобки у `Base[...]`, цикл `class A(A)`, основа-функция, затенение импортированного имени
    собственным классом, правка ответа `of` не меняет индекс. Ожидаемые значения — литералы.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

from scripts.atlas.tests.test_links import _at, _links, _of, _pad

__all__: list[str] = []

_FILES = {
    "pkg/__init__.py": "",
    "pkg/core.py": _pad("class Base:  # @base\n    pass\n"),
    "pkg/fn.py": _pad("def Func():  # @func\n    pass\n"),
    "pkg/use.py": _pad(
        """\
from typing import Dict
from pkg.core import Base
from pkg.fn import Func


class Nested(Base[Dict[str, Base]]):
    pass


class Cycle(Cycle):  # @cycle
    pass


class ViaFunc(Func):
    pass


class Base(Base):  # @shadow
    pass
"""
    ),
}


def _bases(links, ident: str):
    res = _of(links, ident)
    assert res is not None, ident
    return res["bases"]


def test_nested_brackets_resolve_by_name_before_first_bracket():
    links = _links(_FILES)
    assert _bases(links, "pkg/use.py::Nested") == [
        {
            "name": "Base[Dict[str, Base]]",
            "where": _at(_FILES, "pkg/core.py", "base"),
            "how": "import",
            "scope": "prod",
        }
    ]


def test_self_named_base_is_same_file_and_does_not_loop():
    links = _links(_FILES)
    assert _bases(links, "pkg/use.py::Cycle") == [
        {"name": "Cycle", "where": _at(_FILES, "pkg/use.py", "cycle"), "how": "same-file", "scope": "prod"}
    ]


def test_function_as_base_has_no_class_address():
    links = _links(_FILES)
    assert _bases(links, "pkg/use.py::ViaFunc") == [{"name": "Func", "where": None, "how": None, "scope": None}]


def test_own_class_shadowing_import_resolves_to_imported_base():
    """`class Base(Base)` рядом с `from pkg.core import Base`: основа — импортированный класс, не он сам."""
    links = _links(_FILES)
    assert _bases(links, "pkg/use.py::Base") == [
        {"name": "Base", "where": _at(_FILES, "pkg/core.py", "base"), "how": "import", "scope": "prod"}
    ]


def test_mutating_answer_does_not_change_index():
    links = _links(_FILES)
    first = _of(links, "pkg/use.py::Nested")
    assert first is not None
    first["bases"][0]["where"] = "x"
    first["bases"].append({})
    second = _of(links, "pkg/use.py::Nested")
    assert second is not None
    assert second["bases"][0]["where"] == _at(_FILES, "pkg/core.py", "base")
    assert len(second["bases"]) == 1
