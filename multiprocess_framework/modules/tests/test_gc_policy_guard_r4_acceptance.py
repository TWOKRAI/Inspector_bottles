# -*- coding: utf-8 -*-
"""T1-iso / R4: слепая приёмка сканера «изолированных gc-тестов».

Источник истины — ``plans/2026-10-03_lifecycle-owner-scope/task-T1-gc-isolation.md`` (ред. 2),
«DESIGN 4» и абзац «Интерфейс (контракт для слепого тестера)». Тесты написаны ДО реализации и
не смотрят ни её, ни существующий R1–R3 страж: проверяются только две чистые функции

* ``isolated_names(conftest_source) -> frozenset[str]`` — имена из литерала ``collect_ignore``;
* ``r4_violations(path, source, isolated) -> list[str]`` — строки ``"<path>:<line>"``.

Ожидаемые значения — литералы. Места, где спек молчит, не угадываются ассертом (см. комментарии
``ambiguous`` и skip-тесты в конце файла).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.tests import test_gc_policy_guard as g

P = "multiprocess_framework/modules/process_module/tests/test_x.py"
CONFTEST = "multiprocess_framework/modules/process_module/tests/conftest.py"
OTHER = frozenset({"other_file.py"})  # имя, которого нет в путях ниже: изоляции нет


def _src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _line_no(entry: str) -> int:
    return int(entry.rsplit(":", 1)[1])


# --------------------------------------------------------------------------- isolated_names


def test_isolated_names_literal_list_gives_frozenset():
    result = g.isolated_names('collect_ignore = ["a.py", "b.py"]\n')
    assert isinstance(result, frozenset)
    assert result == frozenset({"a.py", "b.py"})


def test_isolated_names_variable_is_not_a_literal():
    source = _src('names = ["a.py"]', "collect_ignore = names")
    with pytest.raises(ValueError):
        g.isolated_names(source)


def test_isolated_names_comprehension_is_not_a_literal():
    source = "collect_ignore = [n for n in ('a.py', 'b.py')]\n"
    with pytest.raises(ValueError):
        g.isolated_names(source)


def test_isolated_names_call_is_not_a_literal():
    source = _src("def make():", "    return ['a.py']", "collect_ignore = make()")
    with pytest.raises(ValueError):
        g.isolated_names(source)


def test_isolated_names_non_string_element_is_not_a_list_of_strings():
    source = _src("NAME = 'a.py'", 'collect_ignore = ["b.py", NAME]')
    with pytest.raises(ValueError):
        g.isolated_names(source)


# ------------------------------------------------------------------- r4_violations: clean


def test_r4_clean_file_gives_empty_list():
    source = _src("import os", "", "def f():", "    return os.getcwd()")
    assert g.r4_violations(P, source, OTHER) == []


def test_r4_other_gc_calls_are_not_r4():
    source = _src("import gc", "", "gc.collect()", "gc.disable()", "n = gc.get_count()")
    assert g.r4_violations(P, source, OTHER) == []


# ------------------------------------------------------------------ r4_violations: forms


def test_r4_gc_freeze_call():
    source = _src("import gc", "", "gc.freeze()")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_gc_unfreeze_call():
    source = _src("import gc", "", "gc.unfreeze()")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_module_alias_import_gc_as_g():
    source = _src("import gc as g", "", "g.unfreeze()")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_from_gc_import_freeze():
    # ambiguous: строка нарушения — import (1) или вызов (3)? Спек требует ровно одно нарушение.
    source = _src("from gc import freeze", "", "freeze()")
    result = g.r4_violations(P, source, OTHER)
    assert len(result) == 1
    assert result[0] in {f"{P}:1", f"{P}:3"}


def test_r4_from_gc_import_with_as_alias():
    source = _src("from gc import unfreeze as thaw", "", "thaw()")
    result = g.r4_violations(P, source, OTHER)
    assert len(result) == 1
    assert result[0] in {f"{P}:1", f"{P}:3"}


def test_r4_getattr_gc_string_name_call():
    source = _src("import gc", "", 'getattr(gc, "unfreeze")()')
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_assignment_of_gc_attribute():
    source = _src("import gc", "", "f = gc.unfreeze")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_suspend_collection_owner_as_name_in_with():
    source = _src("", "", "with suspend_collection_owner():", "    pass")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_suspend_collection_owner_as_attribute_call():
    source = _src("", "", "_door().suspend_collection_owner()")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


def test_r4_suspend_collection_owner_as_attribute_in_with():
    source = _src("", "", "with _door().suspend_collection_owner():", "    pass")
    assert g.r4_violations(P, source, OTHER) == [f"{P}:3"]


# --------------------------------------------------------------- r4_violations: boundaries


def test_r4_several_violations_report_each_with_its_own_line():
    source = _src(
        "import gc",  # 1
        "from x import y",  # 2
        "gc.freeze()",  # 3
        "",  # 4
        "def f():",  # 5
        "    gc.unfreeze()",  # 6
        "    with _door().suspend_collection_owner():",  # 7
        "        pass",  # 8
    )
    result = g.r4_violations(P, source, OTHER)
    assert sorted(result, key=_line_no) == [f"{P}:3", f"{P}:6", f"{P}:7"]


def test_r4_isolated_basename_gives_empty_list():
    source = _src("import gc", "", "gc.unfreeze()", "gc.freeze()")
    assert g.r4_violations(P, source, frozenset({"test_x.py"})) == []


def test_r4_conftest_is_never_isolated_even_if_listed():
    source = _src("import gc", "", "gc.unfreeze()")
    result = g.r4_violations(CONFTEST, source, frozenset({"conftest.py"}))
    assert result == [f"{CONFTEST}:3"]


def test_r4_mention_in_string_is_not_a_violation():
    source = _src("import gc", "", 'SCRIPT = "import gc; gc.unfreeze(); gc.freeze(); suspend_collection_owner()"')
    assert g.r4_violations(P, source, OTHER) == []


def test_r4_mention_in_comment_is_not_a_violation():
    source = _src("import gc", "", "# gc.unfreeze() and suspend_collection_owner() are banned here")
    assert g.r4_violations(P, source, OTHER) == []


def test_r4_mention_in_docstring_is_not_a_violation():
    source = _src(
        '"""Module doc: gc.freeze() and suspend_collection_owner()."""',
        "",
        "def f():",
        '    """Calls gc.unfreeze() according to the doc."""',
        "    return 1",
    )
    assert g.r4_violations(P, source, OTHER) == []


# ------------------------------------------------------------------- ambiguous in spec


@pytest.mark.skip(
    reason=(
        "ambiguous in spec: isolated_names without collect_ignore (frozenset() or ValueError?); "
        "tuple literal as a list?"
    )
)
def test_isolated_names_ambiguous_inputs():
    raise AssertionError("interpretation needed from the spec author")
